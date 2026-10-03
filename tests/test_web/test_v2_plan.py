"""GET /api/v2/plan (issue #165, волна 3)."""

from app.db.models import User
from app.db.models_program import Exercise, Program, ProgramItem
from app.domain.multi_program import MetricType, ProgramStructureType, WeekPhase
from tests.test_web._v2_client import v2_get, v2_post


async def test_get_plan_for_unknown_telegram_id_is_404(session):
    response = await v2_get(session, telegram_id=60101, path="/api/v2/plan")
    assert response.status_code == 404


async def test_get_plan_before_any_inclusion_is_null_not_autocreated(session, user: User):
    """GET не создаёт TrainingPlan молча (побочный эффект на чтении) —
    план появляется только после POST /program-inclusions или
    POST /plan-items, см. докстринг PlanResponse."""
    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")

    assert response.status_code == 200
    assert response.json()["plan"] is None


async def _make_recurring_program_with_items(session, *, category: str = "plan_week_api") -> Program:
    """Тот же рецепт, что tests/test_services/test_plan_week_service.py::
    _make_recurring_program, но с ОДНИМ элементом, закреплённым за днём
    недели (day_of_week=1, вторник по соглашению DashboardScreen.tsx:
    0=понедельник) — до issue #193 ни один реальный ProgramItem не имел
    day_of_week заданным (см. scripts/backfill_multi_program.py), поэтому
    группировку "по дням vs свободный пул" в GET /api/v2/plan раньше не
    на чём было проверить."""
    program = Program(
        name="Синтетическая с днём", goal="test", structure_type=ProgramStructureType.RECURRING,
        category=category, config={},
    )
    session.add(program)
    await session.flush()

    exercise_day = Exercise(name="Со вторника", metric_type=MetricType.REPS, category=category)
    exercise_pool = Exercise(name="Свободное", metric_type=MetricType.REPS, category=category)
    session.add_all([exercise_day, exercise_pool])
    await session.flush()

    session.add_all([
        ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=exercise_day.id,
            count_per_week=1, day_of_week=1,
        ),
        ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=exercise_pool.id,
            count_per_week=3, day_of_week=None,
        ),
    ])
    await session.flush()
    return program


async def test_get_plan_includes_current_plan_week_and_groups_items_by_it(session, user: User):
    """issue #193 (WORKER B) — GET /api/v2/plan раньше не отдавал ни одной
    PlanWeek вообще, хотя ensure_current_plan_week (issue #188, вызывается
    тут же на каждый GET) уже материализует её и проставляет
    PlanItem.plan_week_id. Проверяем оба контракта фронтенда разом: (1)
    plan_weeks непустой и содержит текущую неделю с ожидаемыми полями, (2)
    каждый plan_item реально ссылается на её id (не на week_phase — это
    разные вещи, см. CLAUDE.md/issue #193), включая правильное разделение
    day_of_week vs свободный пул (day_of_week=NULL)."""
    program = await _make_recurring_program_with_items(session)

    await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/program-inclusions",
        payload={"program_id": program.id},
    )

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")
    plan = response.json()["plan"]

    assert len(plan["plan_weeks"]) == 1
    week = plan["plan_weeks"][0]
    assert week["week_number"] == 1
    assert week["phase"] == "base"
    assert week["start_date"]  # материализована реальной сегодняшней датой, не проверяем конкретное число

    assert len(plan["plan_items"]) == 2
    assert all(item["plan_week_id"] == week["id"] for item in plan["plan_items"])

    by_day = [item for item in plan["plan_items"] if item["day_of_week"] is not None]
    free_pool = [item for item in plan["plan_items"] if item["day_of_week"] is None]
    assert [item["day_of_week"] for item in by_day] == [1]
    assert len(free_pool) == 1
