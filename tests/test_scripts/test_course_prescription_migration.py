"""Deploy-level репетиция ревизии e3b9c5d7a2f1 (issue #305, MIGRATION_V2 §3, §5, §7, §8).

Каждый сценарий — своя временная БД и `alembic` подпроцессом (как deploy/deploy-run.sh):
  A. пустая БД → upgrade head: колонка provenance, status вмещает awaiting_assessment;
  B. aged-БД на #304 (d8a3c6f1e2b4) → #307 (f4c1a7e9b3d2, предыдущая ревизия цепочки): инклюзия без block_b.work_sets (цель/снаряд/счётчики свои),
     с null, с уже заданным work_sets, не-STEP → upgrade: дописан ТОЛЬКО недостающий work_sets = 4,
     всё остальное (цели, снаряд, initial_progression_state, status/cursor/rev, история, подписки) —
     байт в байт;
  C. повторный upgrade / downgrade → upgrade = тот же результат (детерминированно), converge после
     миграции и повторный converge = 0 изменений;
  D. downgrade: awaiting_assessment → active, work_sets остаётся (старый код читает его).
"""

import asyncio
import json
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from scripts.repair_plan_convergence import run_all
from tests.test_scripts.test_program_plan_migration import AGED, _exec
from tests.test_scripts.test_system_content_migration import (
    _alembic,
    _fetch,
    _run,
    _scalar,
    deployed_dsn,  # noqa: F401 — фикстура
    scratch_dsn,  # noqa: F401 — фикстура
)

# Aged-строки засеваются на #304 (схема фикстуры AGED), затем БД поднимается до #307 — ревизии, за которой
# идёт e3b9c5d7a2f1 (#307 принят первым, MIGRATION §9.1 — одна голова).
AGED_REVISION = "d8a3c6f1e2b4"
PRE_REVISION = "f4c1a7e9b3d2"
REVISION = "e3b9c5d7a2f1"

_BAND_STATE_B = {
    "target": 5, "volume": 21, "weak_streak": 1, "equipment_type": "band", "equipment_value": "25",
    "equipment_item_id": None, "needs_new_equipment": False, "is_heavy_next": False,
    "heavy_equipment_value_next": None,
}

# Ещё три инклюзии того же плана (неактивные — у плана одна активная): null, заданный 6, не-STEP {}.
EXTRA = f"""
UPDATE program_inclusions SET progression_state = jsonb_set(progression_state, '{{block_b}}',
  CAST('{json.dumps(_BAND_STATE_B)}' AS jsonb)), sequence_cursor = 7, progression_state_rev = 9,
  completed_main_sessions = 3 WHERE id = 3001;
INSERT INTO program_inclusions (id, training_plan_id, program_id, snapshot, progression_state,
  initial_progression_state, started_at, is_active, status)
 SELECT 3002, 2001, program_id, snapshot,
  '{{"strategy_type": "step", "block_a": {{"target": 9, "work_sets": 4}}, "block_b": {{"target": 2, "work_sets": null}}}}',
  '{{}}', started_at, false, 'removed' FROM program_inclusions WHERE id = 3001;
INSERT INTO program_inclusions (id, training_plan_id, program_id, snapshot, progression_state,
  initial_progression_state, started_at, is_active, status)
 SELECT 3003, 2001, program_id, snapshot,
  '{{"strategy_type": "step", "block_a": {{"target": 9, "work_sets": 4}}, "block_b": {{"target": 2, "work_sets": 6}}}}',
  '{{}}', started_at, false, 'removed' FROM program_inclusions WHERE id = 3001;
INSERT INTO program_inclusions (id, training_plan_id, program_id, snapshot, progression_state,
  initial_progression_state, started_at, is_active, status)
 SELECT 3004, 2001, program_id, snapshot, '{{}}', '{{}}', started_at, false, 'removed'
 FROM program_inclusions WHERE id = 3001
"""

# Всё, кроме progression_state, миграция менять не имеет права (MIGRATION_V2 §7 + история).
UNTOUCHED = {
    "users": "id, telegram_id, subscription_status, subscription_expires_at",
    "subscriptions": "*",
    "programs": "id, name, access_level, config, assessment, constraints, slots, frequency",
    "training_sessions": "id, user_id, source, status, performed_at, completed_at, plan_item_id",
    "session_blocks": "*",
    "set_targets": "*",
    "set_logs": "*",
    "plan_items": "*",
    "program_inclusions": "id, training_plan_id, program_id, snapshot, initial_progression_state, started_at, "
    "expires_at, is_active, status, sequence_cursor, progression_state_rev, completed_main_sessions, "
    "last_main_session_at, baseline_assessment_result_id",
}


def _fingerprint(dsn: str) -> dict[str, str]:
    return {
        table: _scalar(
            dsn,
            f"SELECT count(*) || ':' || coalesce(md5(string_agg(x::text, '|' ORDER BY x::text)), '-') "
            f"FROM (SELECT {columns} FROM {table}) x",
        )
        for table, columns in UNTOUCHED.items()
    }


def _states(dsn: str) -> dict[int, dict]:
    return {r.id: r.progression_state for r in _run(_fetch(dsn, "SELECT id, progression_state FROM program_inclusions"))}


def _seed_aged(dsn: str) -> None:
    _alembic(dsn, "upgrade", AGED_REVISION)
    _run(_exec(dsn, AGED))
    _run(_exec(dsn, EXTRA))
    _alembic(dsn, "upgrade", PRE_REVISION)


def test_a_fresh_db_has_provenance_column_and_wide_status(deployed_dsn):  # noqa: F811
    columns = {
        r.column_name: r for r in _run(_fetch(
            deployed_dsn,
            "SELECT column_name, data_type, character_maximum_length FROM information_schema.columns "
            "WHERE table_name = 'program_inclusions' AND column_name IN ('status', 'prescription_provenance')",
        ))
    }
    assert columns["prescription_provenance"].data_type == "jsonb"
    assert columns["status"].character_maximum_length >= len("awaiting_assessment")


def test_b_aged_upgrade_fills_only_missing_block_b_work_sets(scratch_dsn):  # noqa: F811
    _seed_aged(scratch_dsn)
    before_states = _states(scratch_dsn)
    before = _fingerprint(scratch_dsn)

    _alembic(scratch_dsn, "upgrade", REVISION)

    assert _fingerprint(scratch_dsn) == before  # статус/курсор/rev/история/подписки/доступ — байт в байт
    after = _states(scratch_dsn)
    # 3001: поле отсутствовало → 4; цель, снаряд (band 25), счётчики и block_a — прежние.
    assert after[3001]["block_b"] == {**_BAND_STATE_B, "work_sets": 4}
    assert after[3001]["block_a"] == before_states[3001]["block_a"]
    assert {k: v for k, v in after[3001].items() if k != "block_b"} == {
        k: v for k, v in before_states[3001].items() if k != "block_b"
    }
    assert after[3002]["block_b"] == {"target": 2, "work_sets": 4}  # null → 4
    assert after[3003] == before_states[3003]  # заданное значение (6) не перезаписано
    assert after[3004] == {}  # не-STEP не трогается
    assert _scalar(scratch_dsn, "SELECT count(*) FROM program_inclusions WHERE prescription_provenance IS NOT NULL") == 0


def test_c_second_upgrade_and_converge_are_noop(scratch_dsn):  # noqa: F811
    _seed_aged(scratch_dsn)
    _alembic(scratch_dsn, "upgrade", REVISION)
    first = _states(scratch_dsn)
    _alembic(scratch_dsn, "upgrade", REVISION)  # повторный деплой
    _alembic(scratch_dsn, "downgrade", PRE_REVISION)
    _alembic(scratch_dsn, "upgrade", REVISION)  # повторный бэкфилл — детерминированно тот же
    assert _states(scratch_dsn) == first

    async def converge(apply: bool) -> tuple[int, dict]:
        engine = create_async_engine(scratch_dsn)
        try:
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            return await run_all(apply=apply, today=date(2026, 10, 7), session_factory=factory)
        finally:
            await engine.dispose()

    code, applied = asyncio.run(converge(True))
    assert code == 0, applied
    assert _states(scratch_dsn) == first  # convergence состояния прогрессии не трогает
    assert _scalar(scratch_dsn, "SELECT status FROM program_inclusions WHERE id = 3001") == "active"  # aged ≠ замер
    code, again = asyncio.run(converge(True))
    assert code == 0 and again["total_mutations"] == 0, again


def test_d_downgrade_maps_awaiting_to_active_and_keeps_work_sets(scratch_dsn):  # noqa: F811
    _seed_aged(scratch_dsn)
    _alembic(scratch_dsn, "upgrade", REVISION)
    _run(_exec(scratch_dsn, "UPDATE program_inclusions SET status = 'awaiting_assessment' WHERE id = 3001"))
    _alembic(scratch_dsn, "downgrade", PRE_REVISION)
    assert _scalar(scratch_dsn, "SELECT status FROM program_inclusions WHERE id = 3001") == "active"
    assert _states(scratch_dsn)[3001]["block_b"]["work_sets"] == 4


def test_e_single_head_follows_training_session_v2(scratch_dsn):  # noqa: F811
    """#307 (f4c1a7e9b3d2) принят первым: e3b9c5d7a2f1 идёт за ним, голова одна."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PRE_REVISION
    _alembic(scratch_dsn, "upgrade", "head")
    assert _scalar(scratch_dsn, "SELECT version_num FROM alembic_version") == REVISION
