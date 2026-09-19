"""GET /api/dashboard (issue #175) — стартовый экран Mini App вместо сразу
открытой формы тренировки (product-reference skill/docs/architecture-
multicourse.md: Dashboard, не WorkoutScreen). status переиспользует ровно
_resolve_plan_context (тот же путь, что GET /api/workout/plan — покрыт
tests/test_web/test_workout.py), эти тесты фокусируются на том, что этот
эндпойнт добавляет сверху: workouts_count/streak/days_since_last_workout,
честно посчитанные, не выдуманные."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from app.db.models import User
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

BAND_VALUE = Decimal("15.0")


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


async def _get_dashboard(session, telegram_id: int) -> dict:
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/dashboard")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    return response.json()


async def _record_workout(session, user: User, *, performed_at: datetime) -> None:
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=performed_at, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )


async def test_dashboard_for_unknown_telegram_id_is_not_onboarded(session):
    body = await _get_dashboard(session, telegram_id=52001)
    assert body["status"] == "not_onboarded"
    assert body["workouts_count"] == 0
    assert body["streak"] == 0
    assert body["days_since_last_workout"] is None
    assert body["is_first_workout"] is False


async def test_dashboard_first_workout_has_zero_counters(session):
    # Замер есть, ни одной тренировки ещё не было — тот же путь, что
    # GET /api/workout/plan (status="ready", is_first_workout=True), но
    # streak/workouts_count честно нулевые, не "1, потому что замер был".
    user = await UserRepository(session).create(telegram_id=52002, username="fresh")
    now = datetime.now(UTC)
    await BaselineRepository(session).create(user_id=user.id, performed_at=now, reps=10)
    await UserRepository(session).complete_onboarding(user.id, now)
    await SubscriptionService(session).start_trial(user.id, now=now)

    body = await _get_dashboard(session, telegram_id=user.telegram_id)
    assert body["status"] == "ready"
    assert body["is_first_workout"] is True
    assert body["workouts_count"] == 0
    assert body["streak"] == 0
    assert body["days_since_last_workout"] is None


async def test_dashboard_reports_workouts_count_and_days_since_last(session):
    user = await UserRepository(session).create(telegram_id=52003, username="active")
    now = datetime.now(UTC)
    await SubscriptionService(session).start_trial(user.id, now=now)
    await _record_workout(session, user, performed_at=now - timedelta(days=5))

    body = await _get_dashboard(session, telegram_id=user.telegram_id)
    assert body["status"] == "ready"
    assert body["workouts_count"] == 1
    # Одна тренировка — ещё не "серия" в разговорном смысле (тот же принцип,
    # что consecutive_streak_length: длина хвоста считается от 1, но
    # DashboardScreen.tsx показывает число только от 2 — здесь же проверяем
    # сырое число API, оно равно 1, а не 0).
    assert body["streak"] == 1
    assert body["days_since_last_workout"] == 5


async def test_dashboard_streak_counts_consecutive_workouts_without_gap(session):
    # Тот же порог, что app.domain.achievements.consecutive_streak_length
    # использует внутри (GAP_ROLLBACK_DAYS=21) — два подхода с разрывом
    # меньше порога считаются одной серией.
    user = await UserRepository(session).create(telegram_id=52004, username="streaky")
    now = datetime.now(UTC)
    await SubscriptionService(session).start_trial(user.id, now=now)
    await _record_workout(session, user, performed_at=now - timedelta(days=15))
    await _record_workout(session, user, performed_at=now - timedelta(days=5))

    body = await _get_dashboard(session, telegram_id=user.telegram_id)
    assert body["workouts_count"] == 2
    assert body["streak"] == 2
    assert body["days_since_last_workout"] == 5


async def test_dashboard_streak_resets_after_long_gap(session):
    user = await UserRepository(session).create(telegram_id=52005, username="broken-streak")
    now = datetime.now(UTC)
    await SubscriptionService(session).start_trial(user.id, now=now)
    await _record_workout(session, user, performed_at=now - timedelta(days=60))
    await _record_workout(session, user, performed_at=now - timedelta(days=5))

    body = await _get_dashboard(session, telegram_id=user.telegram_id)
    assert body["workouts_count"] == 2
    # Разрыв в 55 дней между тренировками — больше GAP_ROLLBACK_DAYS,
    # хвостовая серия обрывается на последней тренировке, не растёт до 2.
    assert body["streak"] == 1


async def test_dashboard_too_early_status_still_reports_counters(session):
    user = await UserRepository(session).create(telegram_id=52006, username="rested")
    now = datetime.now(UTC)
    await SubscriptionService(session).start_trial(user.id, now=now)
    await _record_workout(session, user, performed_at=now - timedelta(days=1))

    body = await _get_dashboard(session, telegram_id=user.telegram_id)
    assert body["status"] == "too_early"
    assert body["workouts_count"] == 1
    assert body["days_since_last_workout"] == 1
