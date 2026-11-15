"""The exact host diagnostic query is read-only and returns only bounded aggregates."""

import os
import re
import subprocess
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.db.models import EquipmentType
from app.db.models_program import TrainingSession
from app.db.repositories.elective_workouts import ElectiveWorkoutRepository
from app.domain.electives import ElectiveType
from app.services.admin_reset import reset_user_progress
from scripts.backfill_multi_program import seed_catalog
from tests.test_scripts.test_backfill_multi_program import (
    NOW,
    _guarded_database_hashes,
    _record_legacy_workout,
)

GUARD = Path(__file__).resolve().parents[2] / "deploy/deploy-production-guarded-run.sh"
SQL = re.search(
    r"<<'PLANLESS_SOURCE_SQL'\n(.*?)\nPLANLESS_SOURCE_SQL", GUARD.read_text(), re.DOTALL
).group(1)
STATEMENTS = [statement.strip() for statement in SQL.split(";") if statement.strip()]


@pytest_asyncio.fixture(autouse=True)
async def _clean_cold_source_fixture(session):
    yield
    await session.rollback()
    for table in ("workouts_archive_v1", "workout_sets_archive_v1"):
        await session.execute(text(f"DELETE FROM {table} WHERE id=787886"))
    await session.commit()


@pytest.mark.parametrize(
    "source", ["legacy", "reset", "cold_v1", "elective", "native", "active", "unknown"]
)
async def test_literal_host_query_aggregates_synthetic_sources_without_writes(
    session, user, test_dsn, source
):
    await seed_catalog(session)
    if source == "cold_v1":
        await session.execute(
            text("""INSERT INTO workouts_archive_v1
            (id,user_id,workout_set_id,performed_at,status,created_at)
            VALUES (787886,:uid,787886,:now,'completed',:now)"""),
            {"uid": user.id, "now": NOW},
        )
        await session.execute(
            text("""INSERT INTO workout_sets_archive_v1
            (id,user_id,started_from_baseline_id,set_number,workouts_completed,status,started_at)
            VALUES (787886,:uid,787886,1,1,'active',:now)"""),
            {"uid": user.id, "now": NOW},
        )
    elif source in {"legacy", "reset"}:
        await _record_legacy_workout(session, user)
        if source == "reset":
            await reset_user_progress(session, user.id)
    elif source == "elective":
        await ElectiveWorkoutRepository(session).create(
            user_id=user.id,
            elective_type=ElectiveType.MAX_REPS_LADDER,
            performed_at=NOW,
            total_reps=5,
            reps_sequence=[5],
            equipment_type=EquipmentType.BODYWEIGHT,
            equipment_value=None,
        )
    else:
        session.add(
            TrainingSession(
                user_id=user.id,
                source="freeform",
                status="started" if source == "active" else "completed",
                origin=None if source == "unknown" else "native",
                performed_at=NOW,
            )
        )
    await session.commit()
    before = await _guarded_database_hashes(session)
    conn = await asyncpg.connect(test_dsn.replace("postgresql+asyncpg://", "postgresql://"))
    try:
        for statement in STATEMENTS[:-2]:
            await conn.execute(statement)
        assert await conn.fetchval("SHOW transaction_read_only") == "on"
        assert await conn.fetchval("SHOW statement_timeout") == "5s"
        assert await conn.fetchval("SHOW lock_timeout") == "1s"
        fields = list(map(int, (await conn.fetchval(STATEMENTS[-2])).split("|")))
        assert fields[:2] == [1, 1]
        assert len(fields) == 16 and all(value in {0, 1} for value in fields)
        expected_index = {
            "legacy": 2,
            "reset": 6,
            "cold_v1": 5,
            "elective": 3,
            "native": 10,
            "active": 11,
            "unknown": 13,
        }[source]
        assert fields[expected_index] == 1
        if source == "legacy":
            assert fields[7] == 1  # current workout-set progression
        elif source == "reset":
            assert fields[9] == fields[14] == 1  # reset progress and preserved legacy tombstone
        elif source == "cold_v1":
            assert fields[8] == 1  # cold v1 progress
        with pytest.raises(asyncpg.ReadOnlySQLTransactionError):
            await conn.execute("UPDATE users SET username='must-not-write'")
        await conn.execute(STATEMENTS[-1])
    finally:
        await conn.close()
    assert await _guarded_database_hashes(session) == before


def test_diagnostic_has_only_fixed_bounded_read_only_sql():
    assert STATEMENTS[0] == "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert STATEMENTS[-1] == "ROLLBACK"
    assert len(STATEMENTS) == 6
    assert SQL.count("SELECT /*planless-source-aggregate*/") == 1
    assert not re.search(
        r"\b(UPDATE|DELETE|INSERT|CREATE|ALTER|DROP|FOR UPDATE)\b", SQL, re.IGNORECASE
    )


@pytest.mark.parametrize("module", ["json.py", "sitecustomize.py"])
def test_source_diagnostic_parser_never_imports_checkout_code(tmp_path, module):
    source = GUARD.read_text()
    function = source[
        source.index("safe_planless_source_diagnostic() {") : source.index("\nsummary() {")
    ]
    marker = tmp_path / "untrusted-code-executed"
    (tmp_path / module).write_text(
        f"open({str(marker)!r}, 'w').write('private')\nprint('PRIVATE-MODULE')\n"
    )
    script = "exec 7>&1\ndbq() { printf '%s\\n' '1|0|0|0|0|0|0|0|0|0|0|0|0|0|0|0'; }\n"
    proc = subprocess.run(
        ["bash", "-c", script + function + "\nsafe_planless_source_diagnostic"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert proc.returncode == 0 and '"status":"SOURCE_COUNTS"' in proc.stdout
    assert "PRIVATE-MODULE" not in proc.stdout + proc.stderr
    assert not marker.exists()
