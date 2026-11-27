"""Plan-facing seeds must agree with the real API's user-local current week.

Only the seed clock and API calendar are frozen. New plans receive the timestamp
PostgreSQL would record at that instant; existing explicit historical anchors are
preserved. Live engine clocks and the finite visual-fixture harness stay untouched.
"""

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event, select

from app.db.models import User
from app.db.models_program import Exercise, PlanWeek, SessionPlanItem, TrainingPlan, TrainingSession
from app.db.repositories.users import UserRepository
from app.web import routes_v2
from scripts import e2e_seed
from tests.test_web._premium import grant_premium
from tests.test_web._v2_client import v2_get, v2_post

TG = 990_078  # independent of the finite visual-fixture identities
CLOCKS = [
    ("before-local-monday", datetime(2026, 11, 15, 20, 59, 59, tzinfo=UTC)),
    ("local-monday", datetime(2026, 11, 15, 21, 0, tzinfo=UTC)),
    ("after-local-monday", datetime(2026, 11, 15, 21, 0, 1, tzinfo=UTC)),
    ("ci-capture", datetime(2026, 11, 15, 23, 6, tzinfo=UTC)),
    ("before-utc-monday", datetime(2026, 11, 15, 23, 59, 59, tzinfo=UTC)),
    ("utc-monday", datetime(2026, 11, 16, 0, 0, tzinfo=UTC)),
    ("after-utc-monday", datetime(2026, 11, 16, 0, 0, 1, tzinfo=UTC)),
    ("before-local-month", datetime(2027, 1, 31, 20, 59, 59, tzinfo=UTC)),
    ("local-month-monday", datetime(2027, 1, 31, 21, 0, tzinfo=UTC)),
    ("utc-month-monday", datetime(2027, 2, 1, 0, 0, tzinfo=UTC)),
    ("before-local-year", datetime(2028, 12, 31, 20, 59, 59, tzinfo=UTC)),
    ("local-year-monday", datetime(2028, 12, 31, 21, 0, tzinfo=UTC)),
    ("utc-year-monday", datetime(2029, 1, 1, 0, 0, tzinfo=UTC)),
]
# Number of manual occurrences in the API's current week; program rows are API-generated.
SEEDS = [
    ("v2_session_complex", 1),
    ("plan_week_grouping", 2),  # API expands the 2x stretch aggregate
    ("plan_week_manual_session", 2),
    ("journal_combined", 2),
    ("builder_workouts", 6),
    ("live_engine", 5),
    ("journal_plans_polish", 1),
    ("golden_journey", 0),
    ("plan_week_stepper", 3),  # API expands the 2x plank aggregate into two occurrences
]
EXPECTED_MANUAL = {
    "v2_session_complex": {"Комплекс на 3": 1},
    "plan_week_grouping": {"Растяжка": 2},
    "plan_week_manual_session": {"Планка": 1, "Отжимания": 1},
    "journal_combined": {"Планка": 1, "Отжимания": 1},
    "builder_workouts": {
        name: 1
        for name in (
            "Только reps",
            "Только time",
            "Только max",
            "Только interval",
            "Смешанная",
            "Дубли",
        )
    },
    "live_engine": {
        name: 1
        for name in (
            "Движок: подходы",
            "Движок: блоки",
            "Движок: интервал",
            "Движок: пауза",
            "Движок: стоп",
        )
    },
    "journal_plans_polish": {
        "Силовая тренировка верхней части тела с подтягиваниями и отжиманиями": 1
    },
    "golden_journey": {},
    "plan_week_stepper": {"Планка": 2, "Отжимания": 1},
}


def _freeze_calendar(monkeypatch, now, timezone):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)

    monkeypatch.setattr(e2e_seed, "datetime", FrozenDatetime)
    monkeypatch.setattr(
        e2e_seed,
        "_QUESTIONNAIRE_DEFAULTS",
        {
            **e2e_seed._QUESTIONNAIRE_DEFAULTS,
            "timezone": timezone,
        },
    )
    monkeypatch.setattr(routes_v2, "_utcnow", lambda: now)

    def created_at(mapper, connection, plan):
        if plan.created_at is None:
            plan.created_at = now

    event.listen(TrainingPlan, "before_insert", created_at)
    return lambda: event.remove(TrainingPlan, "before_insert", created_at)


@pytest.mark.parametrize("timezone", ["Europe/Moscow", "UTC"])
@pytest.mark.parametrize(("clock_name", "now"), CLOCKS, ids=[name for name, _ in CLOCKS])
@pytest.mark.parametrize(("scenario", "manual_count"), SEEDS, ids=[name for name, _ in SEEDS])
async def test_plan_seed_rows_are_in_api_current_week(
    session,
    monkeypatch,
    timezone,
    clock_name,
    now,
    scenario,
    manual_count,
):
    restore = _freeze_calendar(monkeypatch, now, timezone)
    try:
        await e2e_seed.SCENARIOS[scenario](session, TG)
        await session.commit()
    finally:
        restore()
    user = await UserRepository(session).get_by_telegram_id(TG)
    # journal_edit intentionally fixes its family's profile to Moscow.
    assert user.timezone == ("Europe/Moscow" if scenario == "journal_plans_polish" else timezone)
    local_today = now.astimezone(ZoneInfo(user.timezone)).date()
    monday = local_today - timedelta(days=local_today.weekday())
    plan = (
        await session.execute(
            select(TrainingPlan).where(TrainingPlan.user_id == user.id),
        )
    ).scalar_one()
    weeks = (
        (
            await session.execute(
                select(PlanWeek)
                .where(PlanWeek.training_plan_id == plan.id)
                .order_by(PlanWeek.start_date),
            )
        )
        .scalars()
        .all()
    )
    expected_starts = (
        [monday - timedelta(weeks=1), monday] if scenario == "plan_week_stepper" else [monday]
    )
    response = await v2_get(session, TG, "/api/v2/plan")
    assert response.status_code == 200, response.text
    body = response.json()["plan"]
    assert body["today"] == local_today.isoformat()
    current = next(week for week in body["plan_weeks"] if week["id"] == body["current_week_id"])
    assert current["start_date"] == monday.isoformat()
    manual = [
        item
        for item in body["plan_items"]
        if item["plan_week_id"] == current["id"] and item["program_inclusion_id"] is None
    ]
    assert len(manual) == manual_count
    exercises = dict((await session.execute(select(Exercise.id, Exercise.name))).all())
    names = Counter(item["complex_name"] or exercises[item["exercise_id"]] for item in manual)
    assert names == EXPECTED_MANUAL[scenario]
    assert all(item["count_per_week"] == 1 for item in manual)
    assert [week.start_date for week in weeks] == expected_starts, clock_name
    if scenario in {"journal_plans_polish", "plan_week_stepper"}:
        assert sorted(item["done_count"] for item in manual) == (
            [1] if scenario == "journal_plans_polish" else [0, 0, 1]
        )
    if scenario == "live_engine":
        # The same row selection as startPlanned: current week, then workout title.
        row = next(item for item in manual if item["complex_name"] == "Движок: подходы")
        # Seed onboarding uses the frozen calendar, but Live checks access on its real clock.
        await grant_premium(session, user)
        await session.commit()
        started = await v2_post(
            session,
            TG,
            "/api/v2/sessions/live",
            {
                "client_session_id": str(uuid.uuid4()),
                "plan_item_ids": [row["id"]],
                "engine_version": 2,
            },
        )
        assert started.status_code == 200, started.text
        live = started.json()
        assert live["engine_version"] == 2
        assert live["engine"]["state"]["phase"] == "PREP"
        stored = await session.get(TrainingSession, live["id"])
        assert stored.plan_item_id == row["id"]
        # Calendar injection never reaches the live clock.
        assert abs((stored.performed_at - datetime.now(UTC)).total_seconds()) < 10


@pytest.mark.parametrize(
    "timezone",
    [
        "Europe/Moscow",
        "UTC",
        "Pacific/Kiritimati",
        "America/Los_Angeles",
        None,
        "",
        "invalid/timezone",
    ],
)
@pytest.mark.parametrize(("clock_name", "now"), CLOCKS, ids=[name for name, _ in CLOCKS])
def test_seed_calendar_matches_api_with_timezone_fallback(monkeypatch, timezone, clock_name, now):
    monkeypatch.setattr(routes_v2, "_utcnow", lambda: now)
    user = User(timezone=timezone)
    assert e2e_seed.seed_plan_today(user, now=now) == routes_v2._plan_today(user)


@pytest.mark.parametrize(
    "minutes,seconds", [(0, 0), (0, 1), (0, 59), (1, 0), (4, 59), (5, 0), (5, 1), (126, 0)]
)
async def test_polish_current_week_fact_clamps_only_at_monday_boundary(
    session,
    monkeypatch,
    minutes,
    seconds,
):
    monday_start = datetime(2026, 11, 15, 21, 0, tzinfo=UTC)
    now = monday_start + timedelta(minutes=minutes, seconds=seconds)
    restore = _freeze_calendar(monkeypatch, now, "Europe/Moscow")
    try:
        await e2e_seed.seed_journal_plans_polish(session, TG)
        await session.commit()
    finally:
        restore()
    linked = (
        await session.execute(
            select(TrainingSession).join(
                SessionPlanItem, SessionPlanItem.session_id == TrainingSession.id
            ),
        )
    ).scalar_one()
    assert linked.performed_at == max(now - timedelta(minutes=5), monday_start)
    assert linked.completed_at == max(now - timedelta(minutes=1), monday_start)
    assert linked.performed_at <= linked.completed_at <= now
    assert linked.ended_at is None
    others = (
        (
            await session.execute(
                select(TrainingSession)
                .where(TrainingSession.id != linked.id)
                .order_by(TrainingSession.performed_at),
            )
        )
        .scalars()
        .all()
    )
    assert [item.performed_at for item in others] == [
        now - timedelta(minutes=20),
        now - timedelta(minutes=10),
    ]
    assert [item.completed_at for item in others] == [
        now - timedelta(minutes=19),
        now - timedelta(minutes=9),
    ]
    response = await v2_get(session, TG, "/api/v2/plan")
    assert response.status_code == 200, response.text
    plan = response.json()["plan"]
    current = [
        item for item in plan["plan_items"] if item["plan_week_id"] == plan["current_week_id"]
    ]
    assert [item["done_count"] for item in current] == [1]
