"""Time-dependence of the `plan_week_stepper` E2E seed (parity/full-sweep «Всего тренировок: 8»).

The seed used to put the current week's COMPLETED session at Monday 12:00 UTC. Before that moment the session is
in the future and analytics (`performed_at <= now`) rightly excludes it — the E2E total came out 7, not 8, only
on Monday mornings. The weeks were also derived from the UTC date while the API uses the user's local date.

Wall-clock is frozen by patching `datetime` in `scripts.e2e_seed` (the seed has no clock parameter), so the same
test runs unchanged against the old seed to prove the rollback reproduces the failure.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.db.models_program import PlanWeek, TrainingPlan
from app.db.repositories.training_sessions import TrainingSessionRepository
from app.db.repositories.users import UserRepository
from app.services.training_analytics import TrainingAnalyticsService
from scripts import e2e_seed

MSK = ZoneInfo("Europe/Moscow")  # timezone of every onboarded E2E user (_QUESTIONNAIRE_DEFAULTS)
TELEGRAM_ID = 990_077

# (id, frozen now in UTC). 2026-10-12 is a Monday. MSK = UTC+3 (no DST).
CLOCKS = [
    (
        "monday-before-noon",
        datetime(2026, 10, 12, 5, 0, tzinfo=UTC),
    ),  # Mon 08:00 MSK — the original bug
    ("monday-exactly-noon", datetime(2026, 10, 12, 9, 0, tzinfo=UTC)),  # Mon 12:00 MSK
    ("monday-after-noon", datetime(2026, 10, 12, 15, 30, tzinfo=UTC)),  # Mon 18:30 MSK
    (
        "week-boundary-exact",
        datetime(2026, 10, 11, 21, 0, tzinfo=UTC),
    ),  # Mon 00:00:00 MSK, Sunday in UTC
    ("week-boundary-after", datetime(2026, 10, 11, 21, 0, 1, tzinfo=UTC)),  # Mon 00:00:01 MSK
    ("week-boundary-before", datetime(2026, 10, 11, 20, 59, 59, tzinfo=UTC)),  # Sun 23:59:59 MSK
    (
        "sunday-evening",
        datetime(2026, 10, 18, 18, 0, tzinfo=UTC),
    ),  # Sun 21:00 MSK, last day of the week
]


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _frozen_datetime(fixed: datetime) -> type[datetime]:
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz is not None else fixed.replace(tzinfo=None)

    return FrozenDatetime


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        # Monday 08:00 MSK: noon is still ahead → the session is "now", not the future.
        (datetime(2026, 10, 12, 5, 0, tzinfo=UTC), datetime(2026, 10, 12, 5, 0, tzinfo=UTC)),
        # Monday 18:30 MSK: noon MSK (09:00 UTC) has passed → noon of the week's Monday in the user's tz.
        (datetime(2026, 10, 12, 15, 30, tzinfo=UTC), datetime(2026, 10, 12, 9, 0, tzinfo=UTC)),
        # Boundary: Monday 00:00:00 MSK exactly → the session sits on the week start, same local Monday.
        (datetime(2026, 10, 11, 21, 0, tzinfo=UTC), datetime(2026, 10, 11, 21, 0, tzinfo=UTC)),
    ],
)
def test_performed_at_is_noon_in_user_tz_but_never_after_now(
    now: datetime, expected: datetime
) -> None:
    week_start = _monday(now.astimezone(MSK).date())
    performed_at = e2e_seed.stepper_session_performed_at(week_start, now, MSK)
    assert performed_at == expected
    assert performed_at <= now
    assert performed_at.astimezone(MSK).date() >= week_start  # never leaks into the previous week
    assert performed_at.tzinfo is not None


def test_previous_week_is_noon_monday_in_user_tz() -> None:
    now = datetime(2026, 10, 12, 5, 0, tzinfo=UTC)
    previous_monday = date(2026, 10, 5)
    performed_at = e2e_seed.stepper_session_performed_at(previous_monday, now, MSK)
    assert performed_at == datetime(2026, 10, 5, 9, 0, tzinfo=UTC)  # 12:00 MSK


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "now"), CLOCKS, ids=[name for name, _ in CLOCKS])
async def test_seed_keeps_both_sessions_in_their_weeks_and_counted_by_analytics(
    session,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    now: datetime,
) -> None:
    monkeypatch.setattr(e2e_seed, "datetime", _frozen_datetime(now))
    await e2e_seed.seed_plan_week_stepper(session, TELEGRAM_ID)

    user = await UserRepository(session).get_by_telegram_id(TELEGRAM_ID)
    local_today = now.astimezone(MSK).date()
    current_monday = _monday(local_today)

    # Weeks follow the user's LOCAL date (API `_plan_today`), also when UTC date is still the previous day.
    plan = (
        await session.execute(select(TrainingPlan).where(TrainingPlan.user_id == user.id))
    ).scalar_one()
    starts = sorted(
        (
            await session.execute(
                select(PlanWeek.start_date).where(PlanWeek.training_plan_id == plan.id)
            )
        ).scalars(),
    )
    assert starts == [current_monday - timedelta(weeks=1), current_monday], name

    # Analytics (the source of «Всего тренировок») must count BOTH completed sessions: none is in the future.
    details = await TrainingSessionRepository(session).list_all_completed(user.id)
    assert len(details) == 2, name
    performed = sorted(detail.performed_at for detail in details)
    assert all(moment <= now for moment in performed), f"{name}: session in the future: {performed}"
    assert [moment.astimezone(MSK).date() for moment in performed][1] >= current_monday, name
    assert _monday(performed[0].astimezone(MSK).date()) == current_monday - timedelta(weeks=1), name
    assert _monday(performed[1].astimezone(MSK).date()) == current_monday, name

    series = (
        await TrainingAnalyticsService(session).build(
            user_id=user.id,
            timezone=user.timezone,
            now=now,
            date_from=local_today - timedelta(days=30),
            date_to=local_today,
        )
    )[1]
    assert series.total_workouts == 2, name
