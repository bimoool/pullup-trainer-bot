"""GET /api/profile — вкладка "Профиль" Mini App (issue #45, часть 3):
узкий срез app.bot.handlers.menu.render_profile, тот же
format_subscription_status (не веб-копия текста статуса подписки)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from app.db.repositories.achievements import AchievementRepository
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from app.services.subscription import SubscriptionService
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.main import app


@dataclass
class _FakeWebAppUser:
    id: int
    first_name: str


@dataclass
class _FakeInitData:
    user: _FakeWebAppUser


def _override_dependencies(session, telegram_id: int) -> None:
    app.dependency_overrides[get_validated_init_data] = (
        lambda: _FakeInitData(user=_FakeWebAppUser(id=telegram_id, first_name="Тест"))
    )

    async def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session


async def _get_profile(session, telegram_id: int) -> dict:
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/profile")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    return response.json()


async def test_profile_for_unknown_telegram_id_is_not_onboarded(session):
    body = await _get_profile(session, telegram_id=51001)
    assert body == {
        "is_onboarded": False, "subscription_status_label": None, "coins_balance": None,
        "achievements_count": None, "achievements": [], "workouts_count": None,
        "days_since_last_workout": None,
    }


async def test_profile_for_fresh_user_without_workouts(session):
    user = await UserRepository(session).create(telegram_id=51002, username="fresh")
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))

    body = await _get_profile(session, telegram_id=user.telegram_id)

    assert body["is_onboarded"] is True
    assert body["coins_balance"] == 0
    assert body["achievements_count"] == 0
    assert body["achievements"] == []
    assert body["workouts_count"] == 0
    assert body["days_since_last_workout"] is None
    assert "пробный период" in body["subscription_status_label"]


async def test_profile_reports_workout_and_achievement_counts(session):
    user = await UserRepository(session).create(telegram_id=51003, username="active")
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))
    performed_at = datetime.now(UTC) - timedelta(days=3)
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=performed_at, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=Decimal("20.0"),
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=Decimal("20.0"),
    )
    await AchievementRepository(session).unlock(user_id=user.id, code="first_baseline")

    body = await _get_profile(session, telegram_id=user.telegram_id)

    assert body["workouts_count"] == 1
    assert body["achievements_count"] == 1
    assert body["days_since_last_workout"] == 3


async def test_profile_achievements_include_label_and_date(session):
    """issue #66, п.1 — детали ачивок (код/лейбл/дата) для кликабельного
    счётчика в Mini App, тот же ACHIEVEMENT_LABELS, что render_profile бота."""
    user = await UserRepository(session).create(telegram_id=51004, username="achiever")
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))
    unlocked = await AchievementRepository(session).unlock(user_id=user.id, code="first_baseline")

    body = await _get_profile(session, telegram_id=user.telegram_id)

    assert body["achievements"] == [
        {
            "code": "first_baseline",
            "label": "🎯 Первый замер",
            "unlocked_at": unlocked.unlocked_at.date().isoformat(),
        },
    ]
