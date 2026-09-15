"""GET /api/profile — вкладка "Профиль" Mini App (issue #45, часть 3):
узкий срез app.bot.handlers.menu.render_profile, тот же
format_subscription_status (не веб-копия текста статуса подписки).

PUT /api/profile / GET /api/profile/timezone-options (issue #125) —
правка веса/роста/пола/даты рождения/часового пояса, тот же
UserRepository.update_profile, что и бот (app/bot/handlers/profile_edit.py)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from app.db.models import Gender
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
        "days_since_last_workout": None, "weight_kg": None, "height_cm": None, "gender": None,
        "gender_label": None, "birth_date": None, "age": None, "timezone": None, "timezone_label": None,
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


async def test_profile_includes_profile_fields_when_set(session):
    """issue #125 — те же поля, что показывает app.bot.handlers.menu.render_profile
    текстом (вес/рост/пол/дата рождения/часовой пояс), плюс готовые подписи
    (gender_label/age/timezone_label) тем же кодом, что бот."""
    user = await UserRepository(session).create(telegram_id=51005, username="filled")
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))
    await UserRepository(session).update_profile(
        user.id, weight_kg=Decimal("78.5"), height_cm=180, gender=Gender.MALE,
        birth_date=date(1996, 3, 15), timezone="Europe/Moscow",
    )

    body = await _get_profile(session, telegram_id=user.telegram_id)

    assert body["weight_kg"] == "78.5"
    assert body["height_cm"] == 180
    assert body["gender"] == "male"
    assert body["gender_label"] == "мужской"
    assert body["birth_date"] == "1996-03-15"
    assert body["age"] is not None
    assert body["timezone"] == "Europe/Moscow"
    assert body["timezone_label"] == "Москва (UTC+3)"


async def _put_profile(session, telegram_id: int, payload: dict):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put("/api/profile", json=payload)
    finally:
        app.dependency_overrides.clear()
    return response


async def test_update_profile_for_unknown_user_returns_404(session):
    response = await _put_profile(session, telegram_id=51006, payload={"weight_kg": "80"})
    assert response.status_code == 404


async def test_update_profile_updates_only_provided_fields(session):
    """None-поля (issue #125) — то же самое частичное обновление, что уже
    делает UserRepository.update_profile: второй PUT с одним полем не
    должен стереть значения, заданные первым."""
    user = await UserRepository(session).create(telegram_id=51007, username="editor")
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))

    first = await _put_profile(
        session, user.telegram_id,
        {"weight_kg": "70", "height_cm": 175, "gender": "female", "birth_date": "1998-05-01"},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["weight_kg"] == "70"
    assert body["height_cm"] == 175
    assert body["gender"] == "female"
    assert body["gender_label"] == "женский"
    assert body["birth_date"] == "1998-05-01"

    second = await _put_profile(session, user.telegram_id, {"height_cm": 176})
    assert second.status_code == 200
    body2 = second.json()
    assert body2["height_cm"] == 176
    # Остальные поля из первого PUT не должны были стереться.
    assert body2["weight_kg"] == "70"
    assert body2["gender"] == "female"
    assert body2["birth_date"] == "1998-05-01"


async def test_update_profile_sets_timezone(session):
    user = await UserRepository(session).create(telegram_id=51008, username="tz")
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))

    response = await _put_profile(session, user.telegram_id, {"timezone": "Asia/Yekaterinburg"})

    assert response.status_code == 200
    body = response.json()
    assert body["timezone"] == "Asia/Yekaterinburg"
    assert body["timezone_label"] == "Екатеринбург (UTC+5)"


async def test_update_profile_rejects_invalid_timezone(session):
    user = await UserRepository(session).create(telegram_id=51009, username="badtz")
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))

    response = await _put_profile(session, user.telegram_id, {"timezone": "Not/AZone"})

    assert response.status_code == 422


async def test_update_profile_rejects_future_birth_date(session):
    user = await UserRepository(session).create(telegram_id=51010, username="futuredob")
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))
    future = (datetime.now(UTC).date().replace(year=datetime.now(UTC).date().year + 1)).isoformat()

    response = await _put_profile(session, user.telegram_id, {"birth_date": future})

    assert response.status_code == 422


async def test_update_profile_rejects_non_positive_weight(session):
    user = await UserRepository(session).create(telegram_id=51011, username="badweight")
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))

    response = await _put_profile(session, user.telegram_id, {"weight_kg": "0"})

    assert response.status_code == 422


async def test_get_timezone_options_includes_known_anchors(session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/profile/timezone-options")

    assert response.status_code == 200
    options = {item["value"]: item["label"] for item in response.json()["options"]}
    assert options["Europe/Moscow"] == "Москва (UTC+3)"
