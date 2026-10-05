"""issue #266 — превью расписания программы и «Убрать курс из плана»."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import User
from app.db.models_program import Exercise, PlanItem, Program, ProgramInclusion, ProgramItem
from app.db.repositories.users import UserRepository
from app.domain.multi_program import MetricType, ProgramStructureType, WeekPhase
from tests.test_web._v2_client import v2_get, v2_post


async def _program(session, *, config: dict | None = None, with_items: bool = True) -> Program:
    program = Program(
        name="Курс 266", goal="цель", structure_type=ProgramStructureType.RECURRING,
        category="plan_overview", config=config if config is not None else {},
    )
    session.add(program)
    await session.flush()
    if with_items:
        ex_a = Exercise(name="Подтяг.", metric_type=MetricType.REPS, category="plan_overview", subcategory="block_a")
        ex_b = Exercise(name="Отжим.", metric_type=MetricType.REPS, category="plan_overview")
        session.add_all([ex_a, ex_b])
        await session.flush()
        session.add_all([
            ProgramItem(program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=ex_b.id,
                        count_per_week=1, day_of_week=2),
            ProgramItem(program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=ex_a.id,
                        count_per_week=3, day_of_week=None),
            ProgramItem(program_id=program.id, week_phase=WeekPhase.PEAK, exercise_id=ex_b.id,
                        count_per_week=2, day_of_week=0),
        ])
        await session.flush()
    return program


async def test_schedule_lists_real_items_in_human_form(session, user: User):
    program = await _program(session, config={"block_a": {"base_target": 10, "work_sets": 3}, "duration_weeks": 6})

    response = await v2_get(session, user.telegram_id, f"/api/v2/programs/{program.id}/schedule")

    assert response.status_code == 200
    body = response.json()
    assert body["duration_weeks"] == 6
    assert body["phases"] == ["base", "peak"]
    got = [(i["week_phase"], i["day_of_week"], i["title"], i["count_label"], i["target_label"]) for i in body["items"]]
    assert got == [
        ("base", 2, "Отжим.", "1 раз в неделю", None),
        ("base", None, "Блок A", "3 раза в неделю", "старт: 10 повт. × 3 подх."),
        ("peak", 0, "Отжим.", "2 раза в неделю", None),
    ]


async def test_schedule_without_items_is_empty_not_invented(session, user: User):
    program = await _program(session, with_items=False)

    response = await v2_get(session, user.telegram_id, f"/api/v2/programs/{program.id}/schedule")

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == [] and body["phases"] == [] and body["duration_weeks"] is None


async def test_schedule_unknown_program_and_user_are_404(session, user: User):
    assert (await v2_get(session, user.telegram_id, "/api/v2/programs/999999/schedule")).status_code == 404
    program = await _program(session, with_items=False)
    assert (await v2_get(session, 61001, f"/api/v2/programs/{program.id}/schedule")).status_code == 404


async def test_deactivate_inclusion_keeps_history_and_marks_ended(session, user: User):
    program = await _program(session)
    created = await v2_post(
        session, user.telegram_id, "/api/v2/program-inclusions", {"program_id": program.id},
    )
    inclusion_id = created.json()["id"]
    items_before = (await session.execute(
        select(PlanItem).where(PlanItem.program_inclusion_id == inclusion_id),
    )).scalars().all()
    assert items_before

    response = await v2_post(
        session, user.telegram_id, f"/api/v2/program-inclusions/{inclusion_id}/deactivate", {},
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert response.json()["expires_at"] is not None
    row = await session.get(ProgramInclusion, inclusion_id)
    assert row is not None and row.is_active is False
    items_after = (await session.execute(
        select(PlanItem).where(PlanItem.program_inclusion_id == inclusion_id),
    )).scalars().all()
    assert len(items_after) == len(items_before)

    plan = (await v2_get(session, user.telegram_id, "/api/v2/plan")).json()["plan"]
    listed = [i for i in plan["program_inclusions"] if i["id"] == inclusion_id]
    assert listed and listed[0]["is_active"] is False

    again = await v2_post(
        session, user.telegram_id, f"/api/v2/program-inclusions/{inclusion_id}/deactivate", {},
    )
    assert again.status_code == 200 and again.json()["expires_at"] == response.json()["expires_at"]


async def test_deactivate_foreign_or_unknown_inclusion_is_404_and_untouched(session, user: User):
    other = await UserRepository(session).create(telegram_id=1002, username="other")
    program = await _program(session)
    created = await v2_post(
        session, user.telegram_id, "/api/v2/program-inclusions", {"program_id": program.id},
    )
    inclusion_id = created.json()["id"]

    foreign = await v2_post(
        session, other.telegram_id, f"/api/v2/program-inclusions/{inclusion_id}/deactivate", {},
    )
    unknown = await v2_post(session, user.telegram_id, "/api/v2/program-inclusions/999999/deactivate", {})

    assert foreign.status_code == 404 and unknown.status_code == 404
    row = await session.get(ProgramInclusion, inclusion_id)
    assert row is not None and row.is_active is True


async def test_inclusion_current_week_only_with_explicit_duration(session, user: User):
    fixed = await _program(session, config={"duration_weeks": 4})
    created = await v2_post(session, user.telegram_id, "/api/v2/program-inclusions", {"program_id": fixed.id})
    assert created.json()["duration_weeks"] == 4 and created.json()["current_week"] == 1
    row = await session.get(ProgramInclusion, created.json()["id"])
    row.started_at = datetime.now(UTC) - timedelta(days=15)
    await session.flush()

    plan = (await v2_get(session, user.telegram_id, "/api/v2/plan")).json()["plan"]
    assert plan["program_inclusions"][0]["current_week"] == 3

    open_ended = await _program(session, with_items=False)
    other = await v2_post(session, user.telegram_id, "/api/v2/program-inclusions", {"program_id": open_ended.id})
    assert other.json()["duration_weeks"] is None and other.json()["current_week"] is None
