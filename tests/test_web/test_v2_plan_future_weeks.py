"""#301 — будущие недели продолжающегося курса не пустые: POST /plan/weeks и GET /plan
отдают занятия курса; «Убрать курс» снимает невыполненные будущие занятия.

issue #304 (PROGRAM_PLAN_V2 §6, D8, J12): будущие недели видимы И стартуемы — занятие будущей недели
стартует и засчитывается само (раньше — 422). Одна строка = одно занятие: курс из двух элементов
пула «× 3» — это 3 занятия в неделю (оба элемента — одна тренировка, как и раньше)."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import User
from app.db.models_program import (
    Exercise,
    PlanItem,
    Program,
    ProgramItem,
    TrainingPlan,
    TrainingSession,
)
from app.domain.multi_program import MetricType, ProgramStructureType, WeekPhase
from tests.test_web._v2_client import v2_get, v2_post

TG = 1001


async def _course(session) -> Program:
    program = Program(
        name="Курс 301", goal="цель", structure_type=ProgramStructureType.RECURRING, category="future_weeks", config={},
    )
    session.add(program)
    await session.flush()
    for name in ("Блок A301", "Блок Б301"):
        exercise = Exercise(name=name, metric_type=MetricType.REPS, category="future_weeks")
        session.add(exercise)
        await session.flush()
        session.add(ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=exercise.id, count_per_week=3, day_of_week=None,
        ))
    await session.flush()
    return program


def _by_week(plan: dict) -> dict[int, list[dict]]:
    number_by_id = {w["id"]: w["week_number"] for w in plan["plan_weeks"]}
    out: dict[int, list[dict]] = {}
    for item in plan["plan_items"]:
        out.setdefault(number_by_id[item["plan_week_id"]], []).append(item)
    return out


async def _include(session, user: User) -> int:
    program = await _course(session)
    created = await v2_post(session, user.telegram_id, "/api/v2/program-inclusions", {"program_id": program.id})
    assert created.status_code == 200
    return created.json()["id"]


async def test_future_week_created_by_stepper_has_course_rows_and_get_is_idempotent(session, user: User):
    await _include(session, user)
    plan = (await v2_get(session, user.telegram_id, "/api/v2/plan")).json()["plan"]
    current = plan["plan_weeks"][-1]["week_number"]

    for number in (current + 1, current + 2):
        response = await v2_post(session, user.telegram_id, "/api/v2/plan/weeks", {"week_number": number})
        assert response.status_code == 200

    for _ in range(2):  # повторный GET не плодит строки
        plan = (await v2_get(session, user.telegram_id, "/api/v2/plan")).json()["plan"]
        weeks = _by_week(plan)
        assert [len(weeks[n]) for n in (current, current + 1, current + 2)] == [3, 3, 3]
    assert all(item["program_inclusion_id"] is not None for item in weeks[current + 2])


async def test_readd_after_removal_has_no_ghost_or_duplicate_future_rows(session, user: User):
    inclusion_id = await _include(session, user)
    plan = (await v2_get(session, user.telegram_id, "/api/v2/plan")).json()["plan"]
    current = plan["plan_weeks"][-1]["week_number"]
    await v2_post(session, user.telegram_id, "/api/v2/plan/weeks", {"week_number": current + 1})

    removed = await v2_post(session, user.telegram_id, f"/api/v2/program-inclusions/{inclusion_id}/deactivate", {})
    assert removed.status_code == 200
    plan = (await v2_get(session, user.telegram_id, "/api/v2/plan")).json()["plan"]
    weeks = _by_week(plan)
    # #304 C1: незасчитанные занятия убранного курса в текущей неделе не отдаются (их старт — 422); строки в БД
    # остаются (возобновление вернёт их). Будущая неделя очищена (#301).
    assert current not in weeks and current + 1 not in weeks
    current_ids = sorted((await session.execute(
        select(PlanItem.id).where(PlanItem.program_inclusion_id == inclusion_id, PlanItem.status == "open"),
    )).scalars().all())
    assert len(current_ids) == 3

    program_id = (await session.execute(select(Program.id).where(Program.name == "Курс 301"))).scalar_one()
    again = await v2_post(session, user.telegram_id, "/api/v2/program-inclusions", {"program_id": program_id})
    assert again.status_code == 200
    plan = (await v2_get(session, user.telegram_id, "/api/v2/plan")).json()["plan"]
    # #304 (§2): повторное подключение ВОЗОБНОВЛЯЕТ прежнее включение (не новое), без дублей и «призраков».
    assert again.json()["id"] == inclusion_id
    future = [i for i in plan["plan_items"] if i["program_inclusion_id"] == again.json()["id"]]
    weeks = _by_week({**plan, "plan_items": future})
    assert len(weeks[current]) == 3 and len(weeks[current + 1]) == 3
    assert sorted(i["id"] for i in weeks[current]) == current_ids  # те же занятия, не новые


async def test_course_occurrence_of_future_week_starts_and_credits_itself(session, user: User):
    await _include(session, user)
    plan = (await v2_get(session, user.telegram_id, "/api/v2/plan")).json()["plan"]
    current = plan["plan_weeks"][-1]["week_number"]
    await v2_post(session, user.telegram_id, "/api/v2/plan/weeks", {"week_number": current + 1})
    plan = (await v2_get(session, user.telegram_id, "/api/v2/plan")).json()["plan"]
    weeks = _by_week(plan)

    future = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": [weeks[current + 1][0]["id"]]},
    )

    assert future.status_code == 200, future.text  # J12 / D8: раньше 422
    credited = (await session.execute(
        select(TrainingSession.plan_item_id).where(TrainingSession.id == future.json()["id"]),
    )).scalar_one()
    assert credited == weeks[current + 1][0]["id"]


async def test_copy_week_does_not_duplicate_course_rows(session, user: User):
    await _include(session, user)
    plan = (await v2_get(session, user.telegram_id, "/api/v2/plan")).json()["plan"]
    current_week = plan["plan_weeks"][-1]

    copied = await v2_post(session, user.telegram_id, f"/api/v2/plan/weeks/{current_week['id']}/copy-to-next", {})

    assert copied.status_code == 200 and copied.json()["copied"] == 0
    plan = (await v2_get(session, user.telegram_id, "/api/v2/plan")).json()["plan"]
    assert len(_by_week(plan)[current_week["week_number"] + 1]) == 3


async def test_manual_only_plan_future_week_stays_empty(session, user: User):
    session.add(TrainingPlan(user_id=user.id, created_at=datetime.now(UTC) - timedelta(days=1)))
    await session.flush()
    plan = (await v2_get(session, user.telegram_id, "/api/v2/plan")).json()["plan"]
    current = plan["plan_weeks"][-1]["week_number"]

    response = await v2_post(session, user.telegram_id, "/api/v2/plan/weeks", {"week_number": current + 1})

    assert response.status_code == 200
    count = (await session.execute(select(PlanItem))).scalars().all()
    assert count == []
