"""Analytics E2E history must stay countable at the user's local week boundary.

The Monday 00:30 Kiritimati fixture used to be in the future during the
first half hour of Monday (Sunday 10:00–10:30 UTC), yielding three sessions.
Freeze the seed and analytics to the same instant against real PostgreSQL.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.db.repositories.training_sessions import TrainingSessionRepository
from app.db.repositories.users import UserRepository
from app.services.training_analytics import TrainingAnalyticsService
from scripts import e2e_seed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 11, 15, 9, 59, 59, tzinfo=UTC),  # Sunday locally
        datetime(2026, 11, 15, 10, 0, tzinfo=UTC),  # exactly Monday 00:00
        datetime(2026, 11, 15, 10, 0, 1, tzinfo=UTC),
        datetime(2026, 11, 15, 10, 22, 40, tzinfo=UTC),  # PR #402 CI failure
        datetime(2026, 11, 15, 10, 29, 59, tzinfo=UTC),
        datetime(2026, 11, 15, 10, 30, tzinfo=UTC),
        datetime(2026, 11, 15, 10, 30, 1, tzinfo=UTC),
        datetime(2027, 1, 31, 10, 0, tzinfo=UTC),  # Monday Feb 1 locally
        datetime(2027, 1, 31, 10, 15, tzinfo=UTC),
        datetime(2028, 12, 31, 10, 0, tzinfo=UTC),  # Monday Jan 1 locally
        datetime(2028, 12, 31, 10, 15, tzinfo=UTC),
    ],
)
async def test_analytics_seed_boundary_is_current_week_and_never_future(session, monkeypatch, now):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)

    monkeypatch.setattr(e2e_seed, "datetime", FrozenDatetime)
    await e2e_seed.seed_analytics_v2(session, 910003)
    user = await UserRepository(session).get_by_telegram_id(910003)
    tz = ZoneInfo(user.timezone)
    local_today = now.astimezone(tz).date()
    monday = local_today - timedelta(days=local_today.weekday())
    analytics, series, _, _ = await TrainingAnalyticsService(session).build(
        user_id=user.id,
        timezone=user.timezone,
        now=now,
        date_from=local_today - timedelta(days=29),
        date_to=local_today,
    )
    assert analytics.activity.sessions_last_30_days == 4
    assert analytics.activity.active_days_last_30_days == 4
    assert series.total_workouts == 4
    current_week = analytics.activity.weeks[-1]
    assert current_week.week_start == monday
    assert (current_week.sessions, current_week.active_days) == (1, 1)

    details = await TrainingSessionRepository(session).list_all_completed(user.id)
    assert len(details) == 209  # all 205 old sessions remain, beyond journal pagination
    assert all(detail.performed_at <= now for detail in details)
    boundary = max(detail.performed_at for detail in details)
    scheduled = datetime.combine(monday, datetime.min.time(), tzinfo=tz) + timedelta(minutes=30)
    assert boundary == min(scheduled, now)
    assert boundary.astimezone(tz).date() == monday
    assert boundary.astimezone(UTC).weekday() == 6  # Sunday UTC, Monday locally

    reps = next(panel for panel in analytics.panels if panel.protocol_type == "reps_sets")
    assert (reps.total_reps, reps.set_count, reps.points_total) == (Decimal(1865), 413, 207)
