"""issue #258 — done_count на PlanItem в GET /api/v2/plan: только завершённые
сессии, связанные через SessionPlanItem, на неделе самого item'а (в часовом
поясе пользователя); смешанная сессия считается один раз на каждый item."""

from datetime import UTC, date, datetime, timedelta

from app.db.models import User
from app.db.models_program import (
    Exercise,
    PlanItem,
    PlanWeek,
    SessionPlanItem,
    SessionSource,
    SessionStatus,
    TrainingPlan,
    TrainingSession,
)
from app.domain.multi_program import (
    MetricType,
    WeekPhase,
    count_done_per_plan_item,
    plan_week_number,
    plan_week_start_date,
)
from tests.test_web._v2_client import v2_get


def test_count_done_pure_week_bounds():
    monday = date(2026, 9, 28)
    done = count_done_per_plan_item(
        {1: monday, 2: monday},
        [(1, monday), (1, date(2026, 10, 4)), (1, date(2026, 10, 5)), (1, date(2026, 9, 27)), (99, monday)],
    )
    assert done == {1: 2, 2: 0}


async def _setup(session, user: User):
    exercise = Exercise(name="Планка", metric_type=MetricType.TIME, category="core", source_type="system")
    session.add(exercise)
    plan = TrainingPlan(user_id=user.id, created_at=datetime.now(UTC) - timedelta(days=14))
    session.add(plan)
    await session.flush()
    # Текущую неделю GET создал бы сам (ensure_current_plan_week); создаём
    # заранее по тем же правилам, чтобы привязать к ней items.
    created = plan.created_at.date()
    number = plan_week_number(created, datetime.now(UTC).date())
    weeks = {}
    for n in (number - 1, number):
        week = PlanWeek(
            training_plan_id=plan.id, week_number=n,
            start_date=plan_week_start_date(created, n), phase=WeekPhase.BASE,
        )
        session.add(week)
        weeks[n] = week
    await session.flush()
    current, previous = weeks[number], weeks[number - 1]

    def _item(week, count, day):
        return PlanItem(
            training_plan_id=plan.id, exercise_id=exercise.id, count_per_week=count, day_of_week=day,
            plan_week_id=week.id,
        )

    item_a, item_b, item_prev = _item(current, 3, 0), _item(current, 1, 1), _item(previous, 1, 1)
    session.add_all([item_a, item_b, item_prev])
    await session.flush()
    return current, previous, item_a, item_b, item_prev


async def _session(session, user, items, *, status, performed_at):
    ts = TrainingSession(user_id=user.id, source=SessionSource.PLAN, status=status, performed_at=performed_at)
    session.add(ts)
    await session.flush()
    for item in items:
        session.add(SessionPlanItem(session_id=ts.id, plan_item_id=item.id))
    await session.flush()


def _noon(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=12)


async def test_done_counts(session, user):
    current, previous, item_a, item_b, item_prev = await _setup(session, user)
    start, prev_start = _noon(current.start_date), _noon(previous.start_date)
    await _session(session, user, [item_a], status=SessionStatus.COMPLETED, performed_at=start)
    # смешанная сессия A+B — по одному разу на каждый item
    await _session(session, user, [item_a, item_b], status=SessionStatus.COMPLETED, performed_at=start)
    # незавершённая — не считается
    await _session(session, user, [item_a], status=SessionStatus.STARTED, performed_at=start)
    # завершённая сессия прошлой недели, привязанная к item текущей — вне окна
    await _session(session, user, [item_b], status=SessionStatus.COMPLETED, performed_at=prev_start)
    await _session(session, user, [item_prev], status=SessionStatus.COMPLETED, performed_at=prev_start)
    await session.commit()

    response = await v2_get(session, user.telegram_id, "/api/v2/plan")
    assert response.status_code == 200
    counts = {item["id"]: item["done_count"] for item in response.json()["plan"]["plan_items"]}
    assert counts == {item_a.id: 2, item_b.id: 1, item_prev.id: 1}


async def test_done_counts_use_user_timezone(session, user):
    current, _previous, item_a, _item_b, _item_prev = await _setup(session, user)
    user.timezone = "Pacific/Auckland"  # UTC+12/13: воскресенье 23:00 UTC = понедельник локально
    late_sunday_utc = datetime.combine(current.start_date, datetime.min.time(), tzinfo=UTC) - timedelta(hours=1)
    await _session(session, user, [item_a], status=SessionStatus.COMPLETED, performed_at=late_sunday_utc)
    await session.commit()

    response = await v2_get(session, user.telegram_id, "/api/v2/plan")
    counts = {item["id"]: item["done_count"] for item in response.json()["plan"]["plan_items"]}
    assert counts[item_a.id] == 1
