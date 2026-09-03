"""GET /api/workout/backdate/plan + POST /api/workout/backdate — внесение
тренировки задним числом из Mini App (issue #52, волна 1): та же
WorkoutLogService.record_backdated_workout, что app.bot.handlers.backdate
использует в конце своего сценария (finalize_backdated_workout), не
отдельная веб-копия.

Единственная реальная проверка даты, перенесённая из бота (issue #52,
план) — "не в будущем" (handle_backdate_date/handle_calendar_date_picked:
"parsed_date.date() > datetime.now(UTC).date()"). Лимита "не старше N
дней" в app/bot/handlers/backdate.py на самом деле нет — сюда он тоже не
заводится.

Снаряд по умолчанию наследуется из текущего состояния прогрессии
(resolve_next_targets), с опциональной точечной правкой значения/резины
(actual_weight/actual_band_item_id) — тот же паттерн, что уже есть у
POST /api/workout/submit (issue #45 часть 2/issue #48), а не полный
переспрос типа снаряда, как в app.bot.handlers.equipment._begin_equipment_setup
(упрощение для веба, согласованное в issue #52)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from app.services.subscription import SubscriptionService
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.main import app

BAND_VALUE = Decimal("20.0")


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


async def _get_backdate_plan(session, telegram_id: int) -> dict:
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/workout/backdate/plan")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    return response.json()


async def _post_backdate_raw(session, telegram_id: int, payload: dict):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/workout/backdate", json=payload)
    finally:
        app.dependency_overrides.clear()


async def _post_backdate(session, telegram_id: int, payload: dict) -> dict:
    response = await _post_backdate_raw(session, telegram_id, payload)
    assert response.status_code == 200
    return response.json()


def _backdate_payload(**overrides) -> dict:
    payload = {
        "performed_at": (datetime.now(UTC).date() - timedelta(days=2)).isoformat(),
        "block_a_working_reps": [11, 11, 11], "block_a_max_reps": 12,
        "block_b_working_reps": [4, 4, 4, 4], "block_b_max_reps": 5,
        "comment": None, "confirm_anomalies": False,
    }
    payload.update(overrides)
    return payload


async def _make_returning_user(session, *, telegram_id: int) -> object:
    """Пользователь с подпиской, базовым замером и одной прошлой
    тренировкой на резине (BAND) — needs_new_equipment=False на следующей,
    тот же снаряд наследуется бэкдейтом по умолчанию (см. докстринг
    модуля)."""
    user = await UserRepository(session).create(telegram_id=telegram_id, username="tester")
    now = datetime.now(UTC)
    await SubscriptionService(session).start_trial(user.id, now=now)

    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=now - timedelta(days=10), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=now - timedelta(days=5),
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    return user


# --- GET /api/workout/backdate/plan -------------------------------------------------


async def test_backdate_plan_for_unknown_telegram_id_is_not_onboarded(session):
    body = await _get_backdate_plan(session, telegram_id=54001)
    assert body["status"] == "not_onboarded"


async def test_backdate_plan_without_subscription_is_no_access(session):
    user = await UserRepository(session).create(telegram_id=54002, username="nosub")
    body = await _get_backdate_plan(session, telegram_id=user.telegram_id)
    assert body["status"] == "no_access"


async def test_backdate_plan_without_baseline_is_no_active_set(session):
    user = await UserRepository(session).create(telegram_id=54003, username="nobaseline")
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))
    body = await _get_backdate_plan(session, telegram_id=user.telegram_id)
    assert body["status"] == "no_active_set"


async def test_backdate_plan_is_ready_regardless_of_readiness_gates(session):
    """Ключевое отличие от GET /api/workout/plan (issue #52) — тренировка
    "сегодня" (days_ago=0, MIN_REST_DAYS ещё не прошёл) была бы "too_early"
    для обычного плана, но для бэкдейта эти гейты не применяются вовсе."""
    user = await UserRepository(session).create(telegram_id=54004, username="justtrained")
    now = datetime.now(UTC)
    await SubscriptionService(session).start_trial(user.id, now=now)
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=now, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=now,
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )

    body = await _get_backdate_plan(session, telegram_id=user.telegram_id)
    assert body["status"] == "ready"
    assert body["equipment_a"]["type"] == "band"


async def test_backdate_plan_ready_shows_inherited_equipment(session):
    user = await _make_returning_user(session, telegram_id=54005)
    body = await _get_backdate_plan(session, telegram_id=user.telegram_id)
    assert body["status"] == "ready"
    assert body["equipment_a"]["type"] == "band"
    assert Decimal(body["equipment_a"]["value"]) == BAND_VALUE
    assert body["work_sets_a"] == 3
    assert body["work_sets_b"] == 4


# --- POST /api/workout/backdate ------------------------------------------------------


async def test_backdate_for_unknown_telegram_id_reports_status_without_writing(session):
    body = await _post_backdate(session, telegram_id=54006, payload=_backdate_payload())
    assert body["status"] == "not_onboarded"


async def test_backdate_rejects_future_date(session):
    user = await _make_returning_user(session, telegram_id=54007)
    payload = _backdate_payload(performed_at=(datetime.now(UTC).date() + timedelta(days=1)).isoformat())
    body = await _post_backdate(session, telegram_id=user.telegram_id, payload=payload)
    assert body["status"] == "future_date"

    history = await WorkoutRepository(session).list_for_user(user.id)
    assert len(history) == 1  # только исходная тренировка из _make_returning_user


async def test_backdate_writes_workout_outside_cascade(session):
    user = await _make_returning_user(session, telegram_id=54008)
    payload = _backdate_payload()
    body = await _post_backdate(session, telegram_id=user.telegram_id, payload=payload)

    assert body["status"] == "ok"
    assert body["equipment_a"]["type"] == "band"
    assert Decimal(body["equipment_a"]["value"]) == BAND_VALUE

    history = await WorkoutRepository(session).list_for_user(user.id)
    assert len(history) == 2
    backdated = history[0] if history[0].performed_at < history[1].performed_at else history[1]
    assert backdated.participates_in_cascade is False
    assert backdated.sequence_number is None


async def test_backdate_with_anomaly_requires_confirmation_and_does_not_write(session):
    user = await _make_returning_user(session, telegram_id=54009)
    payload = _backdate_payload(block_a_working_reps=[60, 60, 60], block_a_max_reps=61)

    body = await _post_backdate(session, telegram_id=user.telegram_id, payload=payload)
    assert body["status"] == "anomaly_confirm_required"
    assert body["anomalies_a"]["large_value"] == 61
    history = await WorkoutRepository(session).list_for_user(user.id)
    assert len(history) == 1

    payload["confirm_anomalies"] = True
    body = await _post_backdate(session, telegram_id=user.telegram_id, payload=payload)
    assert body["status"] == "ok"
    history = await WorkoutRepository(session).list_for_user(user.id)
    assert len(history) == 2


async def test_backdate_applies_actual_weight_override_for_weight_block(session):
    user = await UserRepository(session).create(telegram_id=54010, username="weighted")
    now = datetime.now(UTC)
    await SubscriptionService(session).start_trial(user.id, now=now)
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=now - timedelta(days=10), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=now - timedelta(days=5),
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=Decimal("10.0"),
    )

    payload = _backdate_payload(block_b_actual_weight="12.5")
    body = await _post_backdate(session, telegram_id=user.telegram_id, payload=payload)

    assert body["status"] == "ok"
    assert Decimal(body["equipment_b"]["value"]) == Decimal("12.5")


async def test_backdate_applies_actual_band_item_and_rejects_foreign_item(session):
    user = await _make_returning_user(session, telegram_id=54011)
    item = await EquipmentItemRepository(session).create(user_id=user.id, name="моя резина", resistance_kg=None)

    payload = _backdate_payload(block_a_actual_band_item_id=item.id)
    body = await _post_backdate(session, telegram_id=user.telegram_id, payload=payload)
    assert body["status"] == "ok"
    assert body["equipment_a"]["item_id"] == item.id

    other = await UserRepository(session).create(telegram_id=54012, username="other")
    foreign_item = await EquipmentItemRepository(session).create(user_id=other.id, name="чужая", resistance_kg=None)
    payload = _backdate_payload(block_a_actual_band_item_id=foreign_item.id)
    response = await _post_backdate_raw(session, telegram_id=user.telegram_id, payload=payload)
    assert response.status_code == 400


async def test_backdate_plan_includes_band_items_for_band_block(session):
    user = await _make_returning_user(session, telegram_id=54013)
    item = await EquipmentItemRepository(session).create(user_id=user.id, name="широкая", resistance_kg=Decimal("15.0"))

    body = await _get_backdate_plan(session, telegram_id=user.telegram_id)
    assert body["band_items"] == [{"id": item.id, "name": "широкая", "resistance_kg": "15.0"}]
