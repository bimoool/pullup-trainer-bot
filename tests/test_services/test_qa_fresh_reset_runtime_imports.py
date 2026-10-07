"""Regression: the staging bot's «🧪 Fresh reset» dry run refused with 21 × "classified table '<v2 table>' does not
exist in the schema" because the BOT process never imported app.db.models_program, so Base.metadata held only the
17 legacy tables (the web process loads it via routes_v2*). In-process tests could not see it: by the time they run,
pytest has imported models_program through other test modules (test_qa_fresh_reset.py imports it directly).

So this test reproduces the real bot import graph in a FRESH interpreter: it imports only the bot entrypoint
(app.main -> app.bot.handlers -> admin -> app.services.qa_fresh_reset), never models_program or app.db.registry,
then checks the metadata the reset actually uses and runs a real dry run on Postgres. The dry run ends in ROLLBACK,
so the user it inserts never persists.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

V2_TABLES = {
    "assessment_protocols", "assessment_results", "collection_items", "collections", "complex_items", "complexes",
    "exercises", "media_assets", "plan_items", "plan_weeks", "program_inclusions", "program_items", "programs",
    "progression_strategy_profiles", "session_blocks", "session_plan_items", "set_logs", "set_targets",
    "training_plans", "training_sessions", "user_favorites",
}

_SCRIPT = r"""
import asyncio, json, sys
from datetime import UTC, datetime

import app.main  # noqa: F401 — the bot process entrypoint and nothing else

loaded_before_reset = sorted(m for m in ("app.db.models_program", "app.db.registry") if m in sys.modules)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.repositories.users import UserRepository
from app.services.qa_fresh_reset import run_fresh_reset
from app.services.qa_staging_guard import StagingEnvironment
from app.services.subscription import SubscriptionService

DSN, TG = sys.argv[1], 7_000_000_301


async def main():
    engine = create_async_engine(DSN)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            db_name = (await session.execute(text("SELECT current_database()"))).scalar_one()
            user = await UserRepository(session).create(telegram_id=TG, username="runtime_graph")
            await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))
            report = await run_fresh_reset(
                session, telegram_id=TG,
                staging=StagingEnvironment(db_name=db_name, mini_app_host="staging.app.bimoool.com"), apply=False,
            )
            left = (await session.execute(text("SELECT count(*) FROM users WHERE telegram_id = :tg"), {"tg": TG})).scalar_one()
    finally:
        await engine.dispose()
    print(json.dumps({
        "loaded_by_bot_graph": loaded_before_reset,
        "tables": sorted(Base.metadata.tables),
        "ok": report.ok, "guard_failures": report.guard_failures, "left_after_dry_run": left,
    }))


asyncio.run(main())
"""


def test_bot_runtime_import_graph_sees_the_whole_schema_and_dry_run_passes(test_dsn):
    env = {**os.environ, "DATABASE_URL": test_dsn}
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, test_dsn], cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    out = json.loads(result.stdout.strip().splitlines()[-1])

    missing = V2_TABLES - set(out["tables"])
    assert not missing, f"bot runtime metadata lacks v2 tables: {sorted(missing)}"
    assert not [f for f in out["guard_failures"] if "does not exist in the schema" in f], out["guard_failures"]
    assert out["ok"], out["guard_failures"]
    assert out["left_after_dry_run"] == 0  # dry run rolled back the inserted user too
