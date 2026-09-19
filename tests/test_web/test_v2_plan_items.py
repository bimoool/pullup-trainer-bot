"""GET/POST /api/v2/plan-items (issue #165, волна 3) — строки недельной
матрицы, включая копирование ProgramItem -> PlanItem для гипотетической
программы с реальной недельной структурой (не подтягивания — у них
ProgramItem пустой, решение волны 2)."""

from app.db.models import User
from app.db.models_program import Exercise, Program, ProgramItem
from app.domain.multi_program import MetricType, ProgramStructureType, WeekPhase
from tests.test_web._v2_client import v2_get, v2_post


async def _make_weekly_program(session) -> tuple[Program, Exercise]:
    program = Program(
        name="Еженедельная программа", goal="test", structure_type=ProgramStructureType.RECURRING,
        category="weekly_synth", config={},
    )
    session.add(program)
    await session.flush()

    exercise = Exercise(name="Отжимания", metric_type=MetricType.REPS, category="weekly_synth")
    session.add(exercise)
    await session.flush()

    session.add_all([
        ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=exercise.id,
            count_per_week=3, day_of_week=1,
        ),
        ProgramItem(
            program_id=program.id, week_phase=WeekPhase.PEAK, exercise_id=exercise.id,
            count_per_week=1, day_of_week=None,
        ),
    ])
    await session.flush()
    return program, exercise


async def test_list_plan_items_for_unknown_telegram_id_is_404(session):
    response = await v2_get(session, telegram_id=60301, path="/api/v2/plan-items")
    assert response.status_code == 404


async def test_list_plan_items_before_any_plan_is_empty(session, user: User):
    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan-items")
    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_program_inclusion_copies_program_items_into_plan_items(session, user: User):
    program, exercise = await _make_weekly_program(session)

    inclusion_response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/program-inclusions",
        payload={"program_id": program.id},
    )
    inclusion_id = inclusion_response.json()["id"]

    items_response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan-items")
    items = items_response.json()["items"]
    assert len(items) == 2
    assert {(i["count_per_week"], i["day_of_week"], i["week_phase"]) for i in items} == {
        (3, 1, "base"), (1, None, "peak"),
    }
    assert all(i["exercise_id"] == exercise.id for i in items)
    assert all(i["program_inclusion_id"] == inclusion_id for i in items)


async def test_create_plan_item_manually_for_unknown_telegram_id_is_404(session):
    response = await v2_post(
        session, telegram_id=60302, path="/api/v2/plan-items",
        payload={"exercise_id": 1, "count_per_week": 1},
    )
    assert response.status_code == 404


async def test_create_plan_item_manually_has_no_program_inclusion(session, user: User):
    _, exercise = await _make_weekly_program(session)

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
        payload={"exercise_id": exercise.id, "count_per_week": 2, "day_of_week": 3, "week_phase": "rest"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["program_inclusion_id"] is None
    assert body["week_phase"] == "rest"

    listed = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan-items")
    assert len(listed.json()["items"]) == 1


async def test_create_plan_item_rejects_both_exercise_and_complex(session, user: User):
    _, exercise = await _make_weekly_program(session)

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
        payload={"exercise_id": exercise.id, "complex_id": 1, "count_per_week": 1},
    )

    assert response.status_code == 422


async def test_create_plan_item_rejects_neither_exercise_nor_complex(session, user: User):
    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
        payload={"count_per_week": 1},
    )

    assert response.status_code == 422


async def test_list_plan_items_filters_by_program_inclusion_id(session, user: User):
    program, exercise = await _make_weekly_program(session)
    inclusion_response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/program-inclusions",
        payload={"program_id": program.id},
    )
    inclusion_id = inclusion_response.json()["id"]
    await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
        payload={"exercise_id": exercise.id, "count_per_week": 5},
    )

    filtered = await v2_get(
        session, telegram_id=user.telegram_id, path=f"/api/v2/plan-items?program_inclusion_id={inclusion_id}",
    )
    assert len(filtered.json()["items"]) == 2

    unfiltered = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan-items")
    assert len(unfiltered.json()["items"]) == 3
