"""#256 — календарь Журнала: GET /journal/days и фильтр date_from/date_to."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import SessionStatus, TrainingSession
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.domain.journal_calendar import local_range_bounds_utc, month_date_range, parse_month
from app.domain.multi_program import SessionSource
from tests.test_web._v2_client import v2_get
from tests.test_web.test_history import _record_workout
from tests.test_web.test_v2_mixed_workout import _user

MSK = ZoneInfo("Europe/Moscow")


async def _add(session: AsyncSession, user, at: datetime, status: SessionStatus = SessionStatus.COMPLETED) -> int:
    training = TrainingSession(user_id=user.id, source=SessionSource.PLAN, status=status, performed_at=at)
    session.add(training)
    await session.flush()
    return training.id


def test_parse_month_and_bounds():
    assert parse_month("2026-10") == (2026, 10)
    for bad in ("2026-13", "2026-1", "26-10", "2026-10-01", ""):
        with pytest.raises(ValueError):
            parse_month(bad)
    assert month_date_range(2026, 12)[1].isoformat() == "2026-12-31"
    start, end = local_range_bounds_utc(*month_date_range(2026, 10), MSK)
    assert start == datetime(2026, 9, 30, 21, tzinfo=UTC)
    assert end == datetime(2026, 10, 31, 21, tzinfo=UTC)


async def test_days_use_user_timezone_and_skip_unfinished(session: AsyncSession):
    user = await _user(session, 956001)
    # 30.09 21:30 UTC = 01.10 00:30 по Москве -> день 1 октября
    await _add(session, user, datetime(2026, 9, 30, 21, 30, tzinfo=UTC))
    await _add(session, user, datetime(2026, 10, 1, 10, 0, tzinfo=UTC))
    await _add(session, user, datetime(2026, 10, 5, 9, 0, tzinfo=UTC))
    await _add(session, user, datetime(2026, 10, 6, 9, 0, tzinfo=UTC), SessionStatus.STARTED)
    # 31.10 21:30 UTC = 01.11 по Москве -> уже ноябрь
    await _add(session, user, datetime(2026, 10, 31, 21, 30, tzinfo=UTC))

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/journal/days?month=2026-10")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["timezone"] == "Europe/Moscow"
    assert body["days"] == [{"date": "2026-10-01", "count": 2}, {"date": "2026-10-05", "count": 1}]
    assert body["latest_month"] == "2026-11"

    november = (await v2_get(
        session, telegram_id=user.telegram_id, path="/api/v2/journal/days?month=2026-11",
    )).json()
    assert november["days"] == [{"date": "2026-11-01", "count": 1}]


async def test_days_respect_non_default_timezone_and_isolate_users(session: AsyncSession):
    user = await _user(session, 956002)
    other = await _user(session, 956003)
    user.timezone = "America/New_York"
    await session.flush()
    await _add(session, user, datetime(2026, 10, 2, 2, 0, tzinfo=UTC))  # 1 октября 22:00 в Нью-Йорке
    await _add(session, other, datetime(2026, 10, 3, 12, 0, tzinfo=UTC))
    body = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/journal/days?month=2026-10")).json()
    assert body["timezone"] == "America/New_York"
    assert body["days"] == [{"date": "2026-10-01", "count": 1}]


async def test_days_empty_and_invalid_month(session: AsyncSession):
    user = await _user(session, 956004)
    empty = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/journal/days?month=2026-10")
    assert empty.json()["days"] == []
    assert empty.json()["latest_month"] is None
    bad = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/journal/days?month=2026-13")
    assert bad.status_code == 422
    missing = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/journal/days")
    assert missing.status_code == 422


async def test_sessions_date_range_filter_uses_local_days(session: AsyncSession):
    user = await _user(session, 956005)
    oct1_msk = await _add(session, user, datetime(2026, 9, 30, 21, 30, tzinfo=UTC))
    oct5 = await _add(session, user, datetime(2026, 10, 5, 9, 0, tzinfo=UTC))
    await _add(session, user, datetime(2026, 9, 30, 20, 59, tzinfo=UTC))  # 30 сентября МСК
    await _add(session, user, datetime(2026, 10, 31, 21, 0, tzinfo=UTC))  # 1 ноября МСК

    response = await v2_get(
        session, telegram_id=user.telegram_id,
        path="/api/v2/sessions?status=completed&date_from=2026-10-01&date_to=2026-10-31",
    )
    assert response.status_code == 200, response.text
    assert [s["id"] for s in response.json()["sessions"]] == [oct5, oct1_msk]

    one_day = await v2_get(
        session, telegram_id=user.telegram_id,
        path="/api/v2/sessions?status=completed&date_from=2026-10-05&date_to=2026-10-05",
    )
    assert [s["id"] for s in one_day.json()["sessions"]] == [oct5]

    unfiltered = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions?status=completed")
    assert len(unfiltered.json()["sessions"]) == 4


async def test_legacy_workouts_count_in_days_and_history_filter(session: AsyncSession):
    user = await UserRepository(session).create(telegram_id=956006, username="legacy")
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime(2026, 8, 1, tzinfo=UTC), reps=10,
    )
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await _record_workout(session, user.id, workout_set.id, datetime(2026, 9, 12, tzinfo=UTC))
    await _record_workout(session, user.id, workout_set.id, datetime(2026, 10, 3, tzinfo=UTC))
    await _add(session, user, datetime(2026, 10, 3, 9, 0, tzinfo=UTC))

    days = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/journal/days?month=2026-10")).json()
    assert days["days"] == [{"date": "2026-10-03", "count": 2}]
    september = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/journal/days?month=2026-09")).json()
    assert september["days"] == [{"date": "2026-09-12", "count": 1}]

    history = await v2_get(
        session, telegram_id=user.telegram_id, path="/api/history?date_from=2026-10-01&date_to=2026-10-31",
    )
    assert [item["performed_at"] for item in history.json()["items"]] == ["2026-10-03"]
    assert len((await v2_get(session, telegram_id=user.telegram_id, path="/api/history")).json()["items"]) == 2
