"""Общие фикстуры/хелперы для тестов доступности занятий курса (UX-01/02/08/32, CONTRACT_A_B §5).

`enrol_legacy_pre_v56` собирает «форму владельца»: план, инклюзия программы «Подтягивания» с каталожной
частотой 3 в неделю, снимок БЕЗ `slots` и БЕЗ `schedule` (как у подключения до V5.6), `progression_state`
стратегии step, два элемента программы `count_per_week = 3`, `day_of_week = null`; окно плана
материализовано — 3 main-занятия в неделе. Выполненное занятие добавляет вызывающий (`start`/`finish`).

Даты: пользователь в UTC, MON = понедельник 5 окт 2026 (неделя 1 плана), неделя 2 — 12–18 окт."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.db.models import User
from app.db.models_program import (
    Exercise,
    Program,
    ProgramInclusion,
    ProgramItem,
    ProgressionStrategyProfile,
    TrainingPlan,
    TrainingSession,
)
from app.domain.multi_program import MetricType, ProgramStructureType, WeekPhase
from app.domain.progression_strategy import ProgressionStrategyType
from app.services import live_session
from app.web import routes_v2
from tests.test_web._v2_client import v2_get, v2_post

MON = datetime(2026, 10, 5, 10, tzinfo=UTC)


def day(offset: int, *, base: datetime = MON) -> datetime:
    return base + timedelta(days=offset)


def make_clock(monkeypatch):
    def _set(now: datetime) -> None:
        monkeypatch.setattr(routes_v2, "_utcnow", lambda: now)
        monkeypatch.setattr(live_session, "_utcnow", lambda: now)
    return _set


async def pullups_program(session, *, per_item: int = 3, catalogue_per_week: int = 3) -> Program:
    profile = ProgressionStrategyProfile(strategy_type=ProgressionStrategyType.STEP, name="Step UX-A", config={})
    session.add(profile)
    await session.flush()
    program = Program(
        name="Подтягивания", goal="test", structure_type=ProgramStructureType.RECURRING, category="pull_ups",
        progression_strategy_id=profile.id, access_level="free",
        config={"block_a": {"base_target": 10, "work_sets": 3}, "block_b": {"base_target": 3}},
        constraints=[{"spacing_group": "main", "min_days_between_starts": 3}],
        frequency={"sessions_per_week": catalogue_per_week, "per_slot": {}},
    )
    session.add(program)
    await session.flush()
    for name, role in (("Подтягивания — объём", "block_a"), ("Подтягивания — сила", "block_b")):
        exercise = Exercise(name=name, metric_type=MetricType.REPS, category="pull_ups", subcategory=role)
        session.add(exercise)
        await session.flush()
        session.add(ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=exercise.id,
            count_per_week=per_item, day_of_week=None,
        ))
    await session.flush()
    return program


async def enrol_legacy_pre_v56(session, user: User, clock, *, strip_snapshot: bool = True, now: datetime = MON) -> dict:
    """Подключение «Подтягиваний» в устаревшей версии. strip_snapshot — убрать `slots`/`schedule` из снимка
    (форма владельца до V5.6: слоты выводятся из program_items + каталожной частоты)."""
    user.timezone = "UTC"
    session.add(TrainingPlan(user_id=user.id, created_at=MON - timedelta(hours=1)))
    await session.flush()
    clock(now)
    program = await pullups_program(session)
    response = await v2_post(session, user.telegram_id, "/api/v2/program-inclusions", {
        "program_id": program.id, "program_version": "pullups_legacy_step",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    if strip_snapshot:
        inclusion = await session.get(ProgramInclusion, body["id"])
        inclusion.snapshot = {k: v for k, v in inclusion.snapshot.items() if k not in ("slots", "schedule")}
        await session.flush()
    return body


async def get_plan(session, user: User) -> dict:
    response = await v2_get(session, user.telegram_id, "/api/v2/plan")
    assert response.status_code == 200, response.text
    return response.json()["plan"]


def week_items(plan: dict, week_number: int) -> list[dict]:
    week_id = next(w["id"] for w in plan["plan_weeks"] if w["week_number"] == week_number)
    return sorted(
        (i for i in plan["plan_items"] if i["plan_week_id"] == week_id and i["program_slot_key"] == "main"),
        key=lambda i: i["occurrence_index"],
    )


def week_summary(plan: dict, week_number: int) -> dict:
    week_id = next(w["id"] for w in plan["plan_weeks"] if w["week_number"] == week_number)
    return next(s for s in plan["week_summaries"] if s["plan_week_id"] == week_id)


async def ensure_week(session, user: User, week_number: int) -> None:
    response = await v2_post(session, user.telegram_id, "/api/v2/plan/weeks", {"week_number": week_number})
    assert response.status_code == 200, response.text


async def start(session, user: User, plan_item_id: int):
    return await v2_post(session, user.telegram_id, "/api/v2/sessions/live", {
        "client_session_id": str(uuid.uuid4()), "plan_item_ids": [plan_item_id],
    })


async def finish(session, user: User, started, *, performed_at: datetime) -> None:
    session_id = started.json()["id"]
    exercise_id = started.json()["blocks"][0]["exercise_id"]
    batch = await v2_post(
        session, user.telegram_id, f"/api/v2/sessions/live/{session_id}/sets:batch",
        {"sets": [{"set_index": 0, "exercise_id": exercise_id, "value": 10, "block_index": 0}]},
    )
    assert batch.status_code == 200, batch.text
    done = await v2_post(session, user.telegram_id, f"/api/v2/sessions/live/{session_id}/complete", {"abandoned": False})
    assert done.status_code == 200, done.text
    await session.execute(update(TrainingSession).where(TrainingSession.id == session_id).values(performed_at=performed_at))
    await session.flush()


async def do_main(session, user: User, clock, plan_item_id: int, *, at: datetime) -> None:
    """Старт + завершение занятия плана в момент `at` (часы теста ставятся на `at`)."""
    clock(at)
    started = await start(session, user, plan_item_id)
    assert started.status_code == 200, started.text
    await finish(session, user, started, performed_at=at)
