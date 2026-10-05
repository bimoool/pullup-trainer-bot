"""#289 R-5: copy_manual_items переносит строки недели-источника без потерь (в т.ч. одинаковые
exercise/complex/день — разные count), а повторное копирование остаётся идемпотентным."""

from datetime import date

from app.db.models import User
from app.db.models_program import Exercise, PlanItem
from app.db.repositories.training_plans import TrainingPlanRepository
from app.domain.multi_program import MetricType, WeekPhase
from app.services.plan_week import PlanWeekService


async def _setup(session, user: User):
    exercise = Exercise(name="Отжимания", metric_type=MetricType.REPS, category="test_synth")
    session.add(exercise)
    await session.flush()
    plans = TrainingPlanRepository(session)
    plan = await plans.get_or_create_for_user(user.id)
    src = await plans.create_plan_week(
        training_plan_id=plan.id, week_number=1, start_date=date(2026, 9, 21), phase=WeekPhase.BASE)
    dst = await plans.create_plan_week(
        training_plan_id=plan.id, week_number=2, start_date=date(2026, 9, 28), phase=WeekPhase.BASE)
    for count in (2, 3):  # две одинаковые строки (упражнение, день) с разным count
        session.add(PlanItem(
            training_plan_id=plan.id, exercise_id=exercise.id, count_per_week=count, day_of_week=1,
            program_inclusion_id=None, plan_week_id=src.id,
        ))
    await session.flush()
    return plans, src, dst


async def test_copy_preserves_identical_rows_of_source_week(session, user: User):
    plans, src, dst = await _setup(session, user)
    service = PlanWeekService(session)
    copied, skipped = await service.copy_manual_items(source=src, target=dst)
    assert (copied, skipped) == (2, 0)
    counts = sorted(i.count_per_week for i in await plans.list_manual_plan_items_for_week(dst.id))
    assert counts == [2, 3]


async def test_recopy_is_idempotent_with_duplicate_rows(session, user: User):
    plans, src, dst = await _setup(session, user)
    service = PlanWeekService(session)
    await service.copy_manual_items(source=src, target=dst)
    copied, skipped = await service.copy_manual_items(source=src, target=dst)
    assert (copied, skipped) == (0, 2)
    assert len(await plans.list_manual_plan_items_for_week(dst.id)) == 2
