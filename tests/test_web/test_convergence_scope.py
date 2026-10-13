"""Сведение применяется только к подтверждённым пользователям и защищено не одним лишь CLI-фильтром.

* функция ``converge_history_all`` сама отказывается писать без явного списка (не только argparse);
* запись по списку не трогает остальных пользователей, а dry-run по списку и по всем ничего не пишет;
* ``repair_plan_convergence --user-ids`` с неизвестным/без плана id ничего не пишет и завершается кодом 3;
* CLI не принимает ``--all --apply`` и ``--converge-history --apply`` без ``--user-ids``;
* путей «раньше CLI» нет: сведение истории не импортируется ни рантаймом (``app/``, кроме самого сервиса), ни миграциями,
  а миграции не вставляют копии в ``training_sessions``.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models_program import TrainingSession
from scripts.backfill_multi_program import converge_history_all
from scripts.repair_plan_convergence import EXIT_NO_PLAN, run_all
from tests.test_web.test_journal_dedupe import BASE, _free_workout, _legacy_user

ROOT = Path(__file__).resolve().parents[2]


async def _copies(session: AsyncSession, user_id: int) -> int:
    return (await session.execute(
        select(func.count()).select_from(TrainingSession).where(TrainingSession.user_id == user_id),
    )).scalar_one()


async def _user_without_copies(session: AsyncSession, telegram_id: int) -> int:
    user, workout_set = await _legacy_user(session, telegram_id)
    await _free_workout(session, user, workout_set, BASE, 12)
    user_id = user.id
    await session.execute(text("DELETE FROM training_sessions WHERE user_id = :u"), {"u": user_id})  # «копии не было»
    await session.commit()
    return user_id


async def test_apply_without_an_explicit_user_list_is_refused_by_the_function_itself(session: AsyncSession):
    user_id = await _user_without_copies(session, 992001)
    for ids in (None, []):
        with pytest.raises(ValueError, match="explicit non-empty user_ids"):
            await converge_history_all(session, apply=True, user_ids=ids)
    assert await _copies(session, user_id) == 0


async def test_scoped_apply_touches_only_confirmed_users_and_dry_runs_write_nothing(session: AsyncSession):
    confirmed = await _user_without_copies(session, 992002)
    other = await _user_without_copies(session, 992003)

    dry_all = await converge_history_all(session, apply=False)  # discovery по всем: только чтение
    dry_scoped = await converge_history_all(session, apply=False, user_ids=[confirmed])
    assert dry_all["created"] >= 2 and dry_scoped["created"] == 1
    assert (await _copies(session, confirmed), await _copies(session, other)) == (0, 0)

    applied = await converge_history_all(session, apply=True, user_ids=[confirmed])
    assert applied["created"] == 1 and applied["users"] == 1
    assert (await _copies(session, confirmed), await _copies(session, other)) == (1, 0)
    again = await converge_history_all(session, apply=True, user_ids=[confirmed])
    assert not any(again[key] for key in ("classified", "bound", "created", "updated", "superseded", "elective_created"))
    assert await _copies(session, other) == 0


async def test_plan_repair_with_unknown_or_planless_user_id_writes_nothing(session: AsyncSession, test_dsn):
    user_id = await _user_without_copies(session, 992004)  # пользователь есть, плана нет
    engine = create_async_engine(test_dsn)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        for apply in (False, True):
            code, report = await run_all(apply=apply, session_factory=factory, user_ids=[user_id, 987654321])
            assert code == EXIT_NO_PLAN and report["users"] == 0 and "user_ids without a user/plan" in report["error"]
    finally:
        await engine.dispose()


def _cli(*args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    return subprocess.run(
        [sys.executable, "-I", *args], capture_output=True, text=True, env=env, cwd=ROOT, timeout=120, check=False,
        stdin=subprocess.DEVNULL,
    )


def test_cli_refuses_unscoped_apply():
    repair = _cli(str(ROOT / "scripts/repair_plan_convergence.py"), "--all", "--apply")
    assert repair.returncode == 2 and "--all --apply is not allowed" in repair.stderr
    history = _cli(str(ROOT / "scripts/backfill_multi_program.py"), "--converge-history", "--apply")
    assert history.returncode != 0 and "--user-ids" in (history.stderr + history.stdout)
    stray = _cli(str(ROOT / "scripts/backfill_multi_program.py"), "--user-ids", "1")
    assert stray.returncode != 0 and "--converge-history" in (stray.stderr + stray.stdout)
    bad = _cli(str(ROOT / "scripts/backfill_multi_program.py"), "--converge-history", "--user-ids", "1;2")
    assert bad.returncode == 2


def test_history_convergence_has_no_runtime_or_migration_entry_point():
    """Сведение истории запускается только скриптами: приложение и миграции его не импортируют и не вызывают, поэтому
    ни выкат (миграции), ни старт приложения (рантайм) не сводят историю раньше подтверждённого списка."""
    needle = re.compile(r"legacy_history_convergence|converge_history_all|LegacyHistoryConvergenceService|backfill_multi_program")
    offenders = []
    for path in list((ROOT / "app").rglob("*.py")):
        if path.name == "legacy_history_convergence.py":
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if re.match(r"\s*(from|import)\b", line) and needle.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == []
    for path in (ROOT / "app/db/migrations/versions").glob("*.py"):
        text_ = path.read_text()
        assert not re.search(r"^\s*(from|import)\s+.*(legacy_history_convergence|backfill_multi_program)", text_, re.MULTILINE), path
        assert not re.search(r"INSERT\s+INTO\s+training_sessions", text_, re.IGNORECASE), path
