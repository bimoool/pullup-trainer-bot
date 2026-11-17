"""The response-race fixture must open the current month even at Moscow midnight."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.db.repositories.training_sessions import TrainingSessionRepository
from app.db.repositories.users import UserRepository
from scripts import e2e_seed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 10, 31, 21, 0, tzinfo=UTC),
        datetime(2026, 10, 31, 21, 2, tzinfo=UTC),
        datetime(2026, 10, 31, 21, 5, tzinfo=UTC),
        datetime(2026, 12, 31, 21, 0, tzinfo=UTC),
        datetime(2026, 11, 15, 12, 0, tzinfo=UTC),
    ],
)
async def test_response_race_seed_has_one_current_month_session(session, monkeypatch, now):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(e2e_seed, "datetime", FrozenDatetime)
    await e2e_seed.SCENARIOS["journal_calendar_response_race"](session, 939951)
    user = await UserRepository(session).get_by_telegram_id(939951)
    details = await TrainingSessionRepository(session).list_all_completed(user.id)
    local_now = now.astimezone(ZoneInfo(user.timezone))
    current = [
        item
        for item in details
        if item.performed_at.astimezone(ZoneInfo(user.timezone)).strftime("%Y-%m")
        == local_now.strftime("%Y-%m")
    ]
    assert len(current) == 1
    assert current[0].performed_at <= now
    previous = [item for item in details if item not in current]
    assert len(previous) == 4
    previous_month = (local_now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    assert all(
        item.performed_at.astimezone(ZoneInfo(user.timezone)).strftime("%Y-%m") == previous_month
        for item in previous
    )
    assert sorted(
        item.performed_at.astimezone(ZoneInfo(user.timezone)).day for item in previous
    ) == [10, 15, 15, 20]
