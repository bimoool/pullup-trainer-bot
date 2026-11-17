"""The SQL/Python embedded in deploy/rehearse-rest01-release.sh is executed on the owner's host only once, so it is
tested here against the real schema: the unfinished-session scan, the table fingerprint and the row diff."""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.test_web.test_v2_live_engine import _start, clock  # noqa: F401
from tests.test_web.test_v2_live_session import _setup_step_session
from tests.test_web.test_v2_live_session_workout_start import _user

SCRIPT = Path("deploy/rehearse-rest01-release.sh")
SRC = SCRIPT.read_text()


def _embedded(path_var: str, tag: str) -> str:
    return SRC.split(f"cat > \"{path_var}\" <<'{tag}'\n", 1)[1].split(f"\n{tag}\n", 1)[0]


async def _scan(session) -> dict[str, int]:
    out: dict[str, int] = {}
    statements = [s.strip() for s in re.split(r";\s*\n", _embedded("$SQLD/active_wrong_rest.sql", "SQL")) if s.strip()]
    await session.execute(text("drop view if exists rest_scan"))
    for stmt in statements:
        if stmt.startswith("\\echo"):
            continue
        result = await session.execute(text(stmt))
        if result.returns_rows:
            for (value,) in result.all():
                if "|" in value:
                    key, number = value.split("|")
                    out[key] = int(number)
    return out


@pytest.mark.parametrize("generic_90", [False, True])
async def test_unfinished_wrong_rest_scan(session, clock, generic_90):  # noqa: F811
    user = await _user(session, 990011)
    _, _, items = await _setup_step_session(session, user)
    body = await _start(session, user, clock, plan_item_ids=[items["block_a"], items["block_b"]])
    if generic_90:  # a session started before the hotfix: engine_plan carries the generic default
        await session.execute(text(
            "update training_sessions set engine_plan = jsonb_set(jsonb_set(engine_plan, "
            "'{blocks,0,sets,0,rest_after_seconds}', '90'), '{blocks,1,sets,0,rest_after_seconds}', '90') where id = :i",
        ), {"i": body["id"]})
    counts = await _scan(session)
    wrong = 1 if generic_90 else 0
    assert counts["engine_v2_active"] == 1
    assert counts["engine_v2_active_with_generic_90"] == wrong
    assert counts["engine_v2_active_wrong_vs_expected"] == wrong
    assert counts["distinct_users_wrong"] == wrong


async def test_fingerprint_covers_every_table_and_detects_a_single_change(session, clock):  # noqa: F811
    statement = _embedded("$SQLD/fingerprint.sql", "SQL").split("\n\\gexec", 1)[0]
    queries = [row[0] for row in (await session.execute(text(statement))).all()]
    assert len(queries) > 40
    user = await _user(session, 990012)
    probe = next(q for q in queries if "'users|'" in q or q.startswith("select 'users'"))
    before = (await session.execute(text(probe))).scalar_one()
    await session.execute(text("update users set rest_seconds_block_a = 111 where id = :i"), {"i": user.id})
    assert (await session.execute(text(probe))).scalar_one() != before


def test_row_diff_reports_added_removed_and_changed_columns(tmp_path):
    helper = tmp_path / "diff_rows.py"
    helper.write_text(_embedded("$SNAP/diff_rows.py", "PY") + "\n")
    before, after, out = tmp_path / "b.jsonl", tmp_path / "a.jsonl", tmp_path / "d.txt"
    before.write_text("\n".join(json.dumps(r) for r in [{"id": 1, "x": 1, "y": "a"}, {"id": 2, "x": 5, "y": "b"}]) + "\n")
    after.write_text("\n".join(json.dumps(r) for r in [{"id": 1, "x": 2, "y": "a"}, {"id": 3, "x": 9, "y": "c"}]) + "\n")
    done = subprocess.run([sys.executable, "-I", str(helper), str(before), str(after), str(out)], capture_output=True, text=True, check=True)
    assert "added=1 removed=1 changed=1" in done.stdout and '"x": 1' in done.stdout
    assert "changed id=1 col=x" in out.read_text()


def test_pinned_runner_hash_matches_the_runner_in_the_repository():
    pinned = re.search(r'REHEARSE_NEW_RUNNER_SHA256:-([0-9a-f]{64})', SRC).group(1)
    actual = hashlib.sha256(Path("deploy/deploy-production-guarded-run.sh").read_bytes()).hexdigest()
    assert pinned == actual, "update the pin in rehearse-rest01-release.sh (and reinstall the runner) when the runner changes"


def test_script_never_touches_production_paths():
    assert "/root/pullup-trainer-bot" in SRC and 'CANON_PROD_DIR="/root/pullup-trainer-bot"' in SRC
    for forbidden in ("/root/pullup-trainer-bot/", "docker compose -p pullup-trainer-bot", "docker restart", "api.telegram.org/bot"):
        assert forbidden not in SRC.replace('CANON_PROD_DIR="/root/pullup-trainer-bot"', ""), forbidden
    assert 'BASE=' in SRC and "/srv/rehearsal-" in SRC
