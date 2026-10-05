"""CRIMPD #259 — GET /api/v2/analytics/training?from=&to=: недельные ряды
«Тренировки / Минуты», длительность = completed_at - performed_at только в
[1 мин, 6 ч], часовой пояс пользователя, исключения."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.models_program import SessionStatus, TrainingSession
from app.domain.multi_program import SessionSource
from tests.test_web._v2_client import v2_get
from tests.test_web.test_v2_mixed_workout import _user


async def _add(
    session: AsyncSession, user: User, at: datetime, minutes: float | None, *, status: SessionStatus = SessionStatus.COMPLETED,
) -> None:
    session.add(TrainingSession(
        user_id=user.id, source=SessionSource.PLAN, status=status, performed_at=at,
        completed_at=None if minutes is None else at + timedelta(minutes=minutes),
    ))


async def _metrics(session: AsyncSession, user: User, query: str) -> dict:
    response = await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/analytics/training{query}")
    assert response.status_code == 200, response.text
    return response.json()["metrics"]


async def test_weekly_series_for_both_metrics_and_exclusions(session: AsyncSession):
    user = await _user(session, 960001)
    user.timezone = "UTC"
    # Неделя пн 2025-03-03 .. вс 2025-03-09
    await _add(session, user, datetime(2025, 3, 4, 10, tzinfo=UTC), 45)
    await _add(session, user, datetime(2025, 3, 6, 10, tzinfo=UTC), 30.5)
    await _add(session, user, datetime(2025, 3, 7, 10, tzinfo=UTC), None)  # без completed_at
    await _add(session, user, datetime(2025, 3, 7, 12, tzinfo=UTC), 0.5)  # < 1 мин
    await _add(session, user, datetime(2025, 3, 8, 12, tzinfo=UTC), 361)  # > 6 ч
    await _add(session, user, datetime(2025, 3, 9, 12, tzinfo=UTC), 360)  # ровно 6 ч — входит
    await _add(session, user, datetime(2025, 3, 8, 13, tzinfo=UTC), 1, status=SessionStatus.STARTED)  # не завершена
    await _add(session, user, datetime(2025, 3, 12, 10, tzinfo=UTC), 20)  # следующая неделя
    await _add(session, user, datetime(2025, 3, 20, 10, tzinfo=UTC), 20)  # вне диапазона
    await session.commit()

    metrics = await _metrics(session, user, "?from=2025-03-03&to=2025-03-16")
    assert metrics["date_from"] == "2025-03-03" and metrics["date_to"] == "2025-03-16"
    assert [w["week_start"] for w in metrics["weeks"]] == ["2025-03-03", "2025-03-10"]  # понедельники
    first, second = metrics["weeks"]
    assert first["workouts"] == 6  # все завершённые, в т.ч. без данных о времени
    assert first["minutes"] == 435  # 45 + 30.5 (1830 с) + 360, суммирование секунд, потом // 60
    assert second == {"week_start": "2025-03-10", "workouts": 1, "minutes": 20}
    assert metrics["total_workouts"] == 7
    assert metrics["total_minutes"] == 455
    assert metrics["without_duration"] == 3  # None, <1 мин, >6 ч


async def test_range_boundaries_are_inclusive_and_empty_weeks_present(session: AsyncSession):
    user = await _user(session, 960002)
    user.timezone = "UTC"
    await _add(session, user, datetime(2025, 3, 1, 23, 59, tzinfo=UTC), 10)  # день до диапазона
    await _add(session, user, datetime(2025, 3, 2, 0, 0, tzinfo=UTC), 10)  # первый день
    await _add(session, user, datetime(2025, 3, 23, 23, 59, tzinfo=UTC), 10)  # последний день
    await _add(session, user, datetime(2025, 3, 24, 0, 0, tzinfo=UTC), 10)  # день после
    await session.commit()

    metrics = await _metrics(session, user, "?from=2025-03-02&to=2025-03-23")
    assert metrics["total_workouts"] == 2
    # 02.03 (вс) относится к неделе 24.02; пустая неделя 10.03 и 17.03 присутствует
    assert [(w["week_start"], w["workouts"]) for w in metrics["weeks"]] == [
        ("2025-02-24", 1), ("2025-03-03", 0), ("2025-03-10", 0), ("2025-03-17", 1),
    ]


async def test_user_timezone_decides_the_week(session: AsyncSession):
    user = await _user(session, 960003)
    # Вс 2025-03-02 21:30 UTC = пн 2025-03-03 06:30 в Токио → неделя 03.03
    await _add(session, user, datetime(2025, 3, 2, 21, 30, tzinfo=UTC), 20)
    await session.commit()

    user.timezone = "Asia/Tokyo"
    await session.commit()
    tokyo = await _metrics(session, user, "?from=2025-03-01&to=2025-03-09")
    assert [(w["week_start"], w["workouts"]) for w in tokyo["weeks"]] == [("2025-02-24", 0), ("2025-03-03", 1)]

    user.timezone = "UTC"
    await session.commit()
    utc = await _metrics(session, user, "?from=2025-03-01&to=2025-03-09")
    assert [(w["week_start"], w["workouts"]) for w in utc["weeks"]] == [("2025-02-24", 1), ("2025-03-03", 0)]


async def test_default_range_is_last_30_days_and_other_users_excluded(session: AsyncSession):
    owner, stranger = await _user(session, 960004), await _user(session, 960005)
    now = datetime.now(UTC)
    await _add(session, owner, now - timedelta(days=3), 25)
    await _add(session, owner, now - timedelta(days=60), 25)
    await _add(session, stranger, now - timedelta(days=2), 25)
    await session.commit()

    metrics = await _metrics(session, owner, "")
    assert metrics["total_workouts"] == 1 and metrics["total_minutes"] == 25
    assert (datetime.fromisoformat(metrics["date_to"]) - datetime.fromisoformat(metrics["date_from"])).days == 29


async def test_invalid_ranges_are_rejected(session: AsyncSession):
    user = await _user(session, 960006)
    await session.commit()
    for query in ("?from=2025-03-10&to=2025-03-01", "?from=2023-01-01&to=2025-03-01", "?from=oops&to=2025-03-01"):
        response = await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/analytics/training{query}")
        assert response.status_code == 422, query
