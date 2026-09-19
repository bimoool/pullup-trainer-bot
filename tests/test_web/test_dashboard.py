"""GET /api/dashboard — стартовый экран Mini App (issue #175): раньше
приложение открывалось сразу на "Текущем плане" (готовой форме ввода
тренировки), что противоречит принятой архитектуре (стартовый экран —
обзорная витрина, не открытая тренировка). Статус переиспользует тот же
_resolve_plan_context, что и GET /api/workout/plan (см. test_workout.py) —
эти тесты не повторяют весь набор статусов оттуда, только проверяют, что
дашборд видит тот же статус плюс честную статистику (стрик/число
тренировок), без выдуманной недельной квоты.

test_dashboard_first_workout_suggests_band_equipment_for_block_a — прямая
проверка на п.2 issue #175: пользователь, которому по результату замера
нужна резина, должен увидеть это уже в ответе API до формы (сам факт
показа отдельным экраном ДО формы проверяется в e2e, см.
webapp-frontend/e2e/scenarios/first-workout.spec.ts)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from app.db.models import Gender, User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import MIN_REST_DAYS, EquipmentType
from app.domain.session import BlockLog
from app.services.onboarding import OnboardingService
from app.services.subscription import SubscriptionService
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.main import app

BAND_VALUE = Decimal("15.0")

_QUESTIONNAIRE_DEFAULTS = {
    "weight_kg": Decimal(75),
    "height_cm": 180,
    "gender": Gender.MALE,
    "birth_date": date(1995, 1, 1),
    "timezone": "Europe/Moscow",
}


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


async def _make_user_with_workouts(
    session, *, telegram_id: int, days_ago_list: list[int],
) -> User:
    """Заводит пользователя с несколькими прошлыми тренировками — по одной
    на каждый элемент days_ago_list (от старой к новой, как и приходит
    список). Снаряд (BAND, значение ниже порога смены обоих блоков) —
    needs_new_equipment=False на следующей, тот же рецепт, что
    _make_returning_user в tests/test_web/test_workout.py."""
    user = await UserRepository(session).create(telegram_id=telegram_id, username="tester")
    now = datetime.now(UTC)
    await SubscriptionService(session).start_trial(user.id, now=now)

    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=now, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    workouts = WorkoutRepository(session)
    for days_ago in days_ago_list:
        await workouts.record_workout(
            user_id=user.id, workout_set_id=workout_set.id, performed_at=now - timedelta(days=days_ago),
            block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=11),
            block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
            block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
            block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
        )
    return user


async def test_dashboard_for_unknown_telegram_id_is_not_onboarded(session):
    body = await _get_dashboard(session, telegram_id=106001)
    assert body["status"] == "not_onboarded"
    assert body["total_workouts"] == 0
    assert body["streak_days"] == 0


async def test_dashboard_first_workout_suggests_band_equipment_for_block_a(session):
    # Замер на 5 повторений: suggest_starting_equipment(5) даёт (BAND,
    # BODYWEIGHT) — то же самое, что видит пользователь на форме
    # (test_workout.py не покрывает этот конкретный замер, он там не
    # используется), здесь важно именно то, что Dashboard отдаёт тип
    # снаряда блока A ДО того, как пользователь дошёл до формы тренировки.
    user = await UserRepository(session).create(telegram_id=106002, username="fresh")
    now = datetime.now(UTC)
    onboarding = OnboardingService(session)
    await onboarding.record_baseline_and_start(user_id=user.id, performed_at=now, reps=5)
    await onboarding.complete_questionnaire_and_start_trial(user_id=user.id, now=now, **_QUESTIONNAIRE_DEFAULTS)

    body = await _get_dashboard(session, telegram_id=user.telegram_id)

    assert body["status"] == "ready"
    assert body["is_first_workout"] is True
    assert body["equipment_a"]["type"] == "band"
    assert body["equipment_b"]["type"] == "bodyweight"
    # Пустая статистика — честно, не выдумана (issue #175, п.4): ни одной
    # тренировки ещё не было.
    assert body["total_workouts"] == 0
    assert body["streak_days"] == 0
    assert body["workouts_last_7_days"] == 0
    assert body["days_since_last_workout"] is None


async def test_dashboard_too_early_reports_ready_at_and_stats(session):
    user = await _make_user_with_workouts(session, telegram_id=106003, days_ago_list=[1])
    body = await _get_dashboard(session, telegram_id=user.telegram_id)

    assert body["status"] == "too_early"
    expected_ready_at = (
        datetime.now(UTC).date() - timedelta(days=1) + timedelta(days=MIN_REST_DAYS)
    ).isoformat()
    assert body["ready_at"] == expected_ready_at
    assert body["total_workouts"] == 1
    assert body["streak_days"] == 1
    assert body["workouts_last_7_days"] == 1
    assert body["days_since_last_workout"] == 1


async def test_dashboard_ready_shows_target_and_equipment(session):
    user = await _make_user_with_workouts(session, telegram_id=106004, days_ago_list=[5])
    body = await _get_dashboard(session, telegram_id=user.telegram_id)

    assert body["status"] == "ready"
    assert body["target_a"] is not None
    assert body["target_b"] is not None
    assert body["equipment_a"]["type"] == "band"
    assert body["ready_at"] is None
    assert body["total_workouts"] == 1
    assert body["workouts_last_7_days"] == 1
    assert body["days_since_last_workout"] == 5


async def test_dashboard_streak_counts_consecutive_workouts_without_gap(session):
    # Три тренировки подряд, каждая в пределах GAP_ROLLBACK_DAYS(21) от
    # соседней — та же формула, что app.domain.achievements.
    # consecutive_streak_length уже проверяет в tests/test_achievements.py,
    # здесь только то, что дашборд реально её вызывает на полной истории.
    user = await _make_user_with_workouts(session, telegram_id=106005, days_ago_list=[20, 10, 3])
    body = await _get_dashboard(session, telegram_id=user.telegram_id)

    assert body["status"] == "ready"
    assert body["streak_days"] == 3
    assert body["total_workouts"] == 3
    assert body["workouts_last_7_days"] == 1
