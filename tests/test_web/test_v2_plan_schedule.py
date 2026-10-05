"""issue #275 — планирование вперёд: создание будущих недель, перенос между
неделями, копирование ручных строк недели в следующую, ownership."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import User
from app.db.models_program import (
    Exercise,
    PlanItem,
    PlanWeek,
    Program,
    ProgramInclusion,
    TrainingPlan,
)
from app.domain.multi_program import (
    MAX_FUTURE_PLAN_WEEKS,
    MetricType,
    ProgramStructureType,
    WeekPhase,
    is_plannable_week_number,
    plan_week_number,
    plan_week_start_date,
)
from tests.test_web._v2_client import v2_get, v2_patch, v2_post

TG = 1001


def test_plannable_window_pure():
    assert is_plannable_week_number(5, 5)
    assert is_plannable_week_number(5 + MAX_FUTURE_PLAN_WEEKS, 5)
    assert not is_plannable_week_number(5 + MAX_FUTURE_PLAN_WEEKS + 1, 5)
    assert not is_plannable_week_number(4, 5)


async def _setup(session, user: User):
    exercise = Exercise(name="Планка", metric_type=MetricType.TIME, category="core", source_type="system")
    session.add(exercise)
    plan = TrainingPlan(user_id=user.id, created_at=datetime.now(UTC) - timedelta(days=14))
    session.add(plan)
    await session.flush()
    created = plan.created_at.date()
    today = datetime.now(UTC).date()
    number = plan_week_number(created, today)
    weeks = {}
    for n in (number - 1, number):
        weeks[n] = PlanWeek(
            training_plan_id=plan.id, week_number=n,
            start_date=plan_week_start_date(created, n), phase=WeekPhase.BASE,
        )
        session.add(weeks[n])
    await session.flush()
    await session.commit()
    return plan, exercise, number, weeks


def _manual(plan, exercise, week, day):
    return PlanItem(
        training_plan_id=plan.id, exercise_id=exercise.id, count_per_week=1, day_of_week=day,
        plan_week_id=week.id,
    )


async def _program_inclusion(session, plan):
    program = Program(name="П", goal="g", structure_type=ProgramStructureType.RECURRING, category="c")
    session.add(program)
    await session.flush()
    inclusion = ProgramInclusion(training_plan_id=plan.id, program_id=program.id, snapshot={}, progression_state={})
    session.add(inclusion)
    await session.flush()
    return inclusion


async def test_create_future_weeks_on_demand_and_window(session, user):
    plan, _, number, _ = await _setup(session, user)

    response = await v2_post(session, TG, "/api/v2/plan/weeks", {"week_number": number + 2})
    assert response.status_code == 200
    assert response.json()["week_number"] == number + 2

    # промежуточные недели созданы, повтор идемпотентен
    again = await v2_post(session, TG, "/api/v2/plan/weeks", {"week_number": number + 2})
    assert again.json()["id"] == response.json()["id"]
    numbers = sorted(
        (await session.execute(select(PlanWeek.week_number).where(PlanWeek.training_plan_id == plan.id))).scalars(),
    )
    assert numbers == [number - 1, number, number + 1, number + 2]

    assert (await v2_post(session, TG, "/api/v2/plan/weeks", {"week_number": number + 5})).status_code == 422
    assert (await v2_post(session, TG, "/api/v2/plan/weeks", {"week_number": number - 1})).status_code == 422

    plan_json = (await v2_get(session, TG, "/api/v2/plan")).json()["plan"]
    assert [w["week_number"] for w in plan_json["plan_weeks"]][-1] == number + 2


async def test_move_manual_item_to_future_week(session, user):
    plan, exercise, number, weeks = await _setup(session, user)
    item = _manual(plan, exercise, weeks[number], 0)
    session.add(item)
    await session.commit()
    future = (await v2_post(session, TG, "/api/v2/plan/weeks", {"week_number": number + 1})).json()

    response = await v2_patch(
        session, TG, f"/api/v2/plan-items/{item.id}", {"day_of_week": 3, "plan_week_id": future["id"]},
    )
    assert response.status_code == 200
    assert response.json()["plan_week_id"] == future["id"]
    assert response.json()["day_of_week"] == 3

    # без plan_week_id неделя не меняется
    same = await v2_patch(session, TG, f"/api/v2/plan-items/{item.id}", {"day_of_week": 4})
    assert same.json()["plan_week_id"] == future["id"]


async def test_move_to_past_week_or_from_past_week_rejected(session, user):
    plan, exercise, number, weeks = await _setup(session, user)
    current_item = _manual(plan, exercise, weeks[number], 0)
    past_item = _manual(plan, exercise, weeks[number - 1], 0)
    session.add_all([current_item, past_item])
    await session.commit()

    to_past = await v2_patch(
        session, TG, f"/api/v2/plan-items/{current_item.id}",
        {"day_of_week": 0, "plan_week_id": weeks[number - 1].id},
    )
    assert to_past.status_code == 422
    from_past = await v2_patch(
        session, TG, f"/api/v2/plan-items/{past_item.id}",
        {"day_of_week": 0, "plan_week_id": weeks[number].id},
    )
    assert from_past.status_code == 422


async def test_move_program_item_across_weeks_is_404(session, user):
    plan, exercise, number, weeks = await _setup(session, user)
    inclusion = await _program_inclusion(session, plan)
    item = _manual(plan, exercise, weeks[number], 0)
    item.program_inclusion_id = inclusion.id
    session.add(item)
    await session.commit()
    future = (await v2_post(session, TG, "/api/v2/plan/weeks", {"week_number": number + 1})).json()

    response = await v2_patch(
        session, TG, f"/api/v2/plan-items/{item.id}", {"day_of_week": 1, "plan_week_id": future["id"]},
    )
    assert response.status_code == 404


async def test_copy_week_copies_manual_only_and_skips_duplicates(session, user):
    plan, exercise, number, weeks = await _setup(session, user)
    inclusion = await _program_inclusion(session, plan)
    program_item = _manual(plan, exercise, weeks[number], 2)
    program_item.program_inclusion_id = inclusion.id
    session.add_all([_manual(plan, exercise, weeks[number], 0), _manual(plan, exercise, weeks[number], 1), program_item])
    await session.commit()

    first = await v2_post(session, TG, f"/api/v2/plan/weeks/{weeks[number].id}/copy-to-next", {})
    assert first.status_code == 200
    body = first.json()
    assert (body["copied"], body["skipped"]) == (2, 0)
    assert body["target_week"]["week_number"] == number + 1

    second = await v2_post(session, TG, f"/api/v2/plan/weeks/{weeks[number].id}/copy-to-next", {})
    assert (second.json()["copied"], second.json()["skipped"]) == (0, 2)

    target_items = (await session.execute(
        select(PlanItem).where(PlanItem.plan_week_id == body["target_week"]["id"]),
    )).scalars().all()
    assert sorted(i.day_of_week for i in target_items) == [0, 1]
    assert all(i.program_inclusion_id is None for i in target_items)


async def test_copy_beyond_window_is_422(session, user):
    _, _, number, _ = await _setup(session, user)
    last = (await v2_post(
        session, TG, "/api/v2/plan/weeks", {"week_number": number + MAX_FUTURE_PLAN_WEEKS},
    )).json()
    response = await v2_post(session, TG, f"/api/v2/plan/weeks/{last['id']}/copy-to-next", {})
    assert response.status_code == 422


async def test_ownership_foreign_week_is_404(session, user):
    from app.db.repositories.users import UserRepository

    plan, exercise, number, weeks = await _setup(session, user)
    item = _manual(plan, exercise, weeks[number], 0)
    session.add(item)
    await session.commit()
    other = await UserRepository(session).create(telegram_id=2002, username="other")
    session.add(TrainingPlan(user_id=other.id))
    await session.commit()

    assert (await v2_post(session, 2002, f"/api/v2/plan/weeks/{weeks[number].id}/copy-to-next", {})).status_code == 404
    moved = await v2_patch(
        session, 2002, f"/api/v2/plan-items/{item.id}", {"day_of_week": 1, "plan_week_id": weeks[number].id},
    )
    assert moved.status_code == 404
