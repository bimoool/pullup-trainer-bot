"""GET /api/workout/backdate/plan + POST /api/workout/backdate — "Внести
пропущенную тренировку" в Mini App (issue #52): тонкая обвязка вокруг
WorkoutLogService.record_backdated_workout, тот же сервис, что
finalize_backdated_workout бота (app/bot/handlers/backdate.py).

Единственная проверка даты — "не в будущем" (issue #52, комментарий
от 2026-09-03: более раннее упоминание лимита в 7 дней было ошибкой по
памяти, в реальном коде бота такого лимита нет). Снаряд для бэкдейта
переспрашивается ВСЕГДА явно — GET .../plan отдаёт цель/снаряд только как
пример для формы, POST не наследует их молча (в отличие от
POST /api/workout/submit)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from app.db.models import BlockType
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


async def _make_returning_user(session, *, telegram_id: int, days_ago: int = 1):
    """Пользователь с одной прошлой тренировкой (блок A на резине) —
    days_ago=1 намеренно близко к "сейчас": бэкдейт не должен упираться в
    too_early/gap_retest_required (issue #52, эти гейты про СЛЕДУЮЩУЮ живую
    тренировку, не про запись прошлой)."""
    user = await UserRepository(session).create(telegram_id=telegram_id, username="tester")
    now = datetime.now(UTC)
    await SubscriptionService(session).start_trial(user.id, now=now)

    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=now, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=now - timedelta(days=days_ago),
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    return user


# --- GET /api/workout/backdate/plan --------------------------------------------------


async def test_backdate_plan_for_unknown_telegram_id_is_not_onboarded(session):
    body = await _get_backdate_plan(session, telegram_id=55001)
    assert body["status"] == "not_onboarded"


async def test_backdate_plan_without_subscription_is_no_access(session):
    user = await UserRepository(session).create(telegram_id=55002, username="nosub")
    body = await _get_backdate_plan(session, telegram_id=user.telegram_id)
    assert body["status"] == "no_access"


async def test_backdate_plan_without_history_is_first_workout(session):
    """Реальный баг issue #123: без единой прошлой тренировки
    resolve_next_targets вернул бы needs_new_equipment=True с BAND без
    item_id (резину физически неоткуда взять, band_items пуст) — раньше это
    молча превращалось в status="ready" с этим снарядом-заглушкой, форма
    вела в тупик 400 при попытке сохранить. Теперь тот же статус, что у
    GET /api/workout/plan для того же пользователя (test_plan_without_history_is_first_workout)."""
    user = await UserRepository(session).create(telegram_id=55015, username="fresh")
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))
    body = await _get_backdate_plan(session, telegram_id=user.telegram_id)
    assert body["status"] == "first_workout"


async def test_backdate_plan_equipment_setup_required_is_reported(session):
    """needs_new_equipment теперь так же строго блокирует бэкдейт, как
    основной GET /api/workout/plan (issue #123) — тот же приём, что
    test_plan_equipment_setup_required_is_reported в test_workout.py:
    (20, 20, 20) достигает equipment_change_threshold блока на объём на
    единственной прошлой тренировке."""
    user = await UserRepository(session).create(telegram_id=55016, username="tester")
    now = datetime.now(UTC)
    await SubscriptionService(session).start_trial(user.id, now=now)
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=now, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=now - timedelta(days=5),
        block_a_reps=BlockLog(working_reps=(20, 20, 20), max_reps=21),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    body = await _get_backdate_plan(session, telegram_id=user.telegram_id)
    assert body["status"] == "equipment_setup_required"


async def test_backdate_plan_ignores_too_early_gate(session):
    """GET /api/workout/plan для того же пользователя вернул бы
    "too_early" (см. test_plan_too_early_is_reported в test_workout.py) —
    бэкдейт этот гейт игнорирует намеренно (issue #52)."""
    user = await _make_returning_user(session, telegram_id=55003, days_ago=1)
    body = await _get_backdate_plan(session, telegram_id=user.telegram_id)
    assert body["status"] == "ready"


async def test_backdate_plan_ignores_gap_retest_required_gate(session):
    user = await _make_returning_user(session, telegram_id=55004, days_ago=40)
    body = await _get_backdate_plan(session, telegram_id=user.telegram_id)
    assert body["status"] == "ready"


async def test_backdate_plan_ready_includes_target_and_band_items(session):
    user = await _make_returning_user(session, telegram_id=55005, days_ago=5)
    item = await EquipmentItemRepository(session).create(user_id=user.id, name="резина", resistance_kg=Decimal("10.0"))

    body = await _get_backdate_plan(session, telegram_id=user.telegram_id)

    assert body["status"] == "ready"
    assert body["work_sets_a"] == 3
    assert body["work_sets_b"] == 4
    assert body["equipment_a"]["type"] == "band"
    assert body["band_items"] == [{"id": item.id, "name": "резина", "resistance_kg": "10.0"}]


# --- POST /api/workout/backdate -------------------------------------------------------


async def test_backdate_submit_for_unknown_telegram_id_reports_status_without_writing(session):
    payload = {
        "performed_at": (datetime.now(UTC).date() - timedelta(days=2)).isoformat(),
        "block_a_working_reps": [11, 11, 11], "block_a_max_reps": 12,
        "block_b_working_reps": [4, 4, 4, 4], "block_b_max_reps": 4,
        "block_a_equipment_type": "band", "block_a_equipment_item_id": None,
        "block_b_equipment_type": "bodyweight",
        "comment": None, "confirm_anomalies": False,
    }
    body = await _post_backdate(session, telegram_id=99998, payload=payload)
    assert body["status"] == "not_onboarded"


async def test_backdate_submit_rejects_future_date(session):
    user = await _make_returning_user(session, telegram_id=55006, days_ago=5)
    payload = {
        "performed_at": (datetime.now(UTC).date() + timedelta(days=1)).isoformat(),
        "block_a_working_reps": [11, 11, 11], "block_a_max_reps": 12,
        "block_b_working_reps": [4, 4, 4, 4], "block_b_max_reps": 4,
        "block_a_equipment_type": "bodyweight",
        "block_b_equipment_type": "bodyweight",
        "comment": None, "confirm_anomalies": False,
    }
    response = await _post_backdate_raw(session, telegram_id=user.telegram_id, payload=payload)
    assert response.status_code == 400


async def test_backdate_submit_requires_weight_value_for_weight_type(session):
    user = await _make_returning_user(session, telegram_id=55007, days_ago=5)
    payload = {
        "performed_at": (datetime.now(UTC).date() - timedelta(days=2)).isoformat(),
        "block_a_working_reps": [11, 11, 11], "block_a_max_reps": 12,
        "block_b_working_reps": [4, 4, 4, 4], "block_b_max_reps": 4,
        "block_a_equipment_type": "weight",
        "block_b_equipment_type": "bodyweight",
        "comment": None, "confirm_anomalies": False,
    }
    response = await _post_backdate_raw(session, telegram_id=user.telegram_id, payload=payload)
    assert response.status_code == 400


async def test_backdate_submit_requires_valid_band_item_for_band_type(session):
    user = await _make_returning_user(session, telegram_id=55008, days_ago=5)
    payload = {
        "performed_at": (datetime.now(UTC).date() - timedelta(days=2)).isoformat(),
        "block_a_working_reps": [11, 11, 11], "block_a_max_reps": 12,
        "block_b_working_reps": [4, 4, 4, 4], "block_b_max_reps": 4,
        "block_a_equipment_type": "band",
        "block_b_equipment_type": "bodyweight",
        "comment": None, "confirm_anomalies": False,
    }
    response = await _post_backdate_raw(session, telegram_id=user.telegram_id, payload=payload)
    assert response.status_code == 400


async def test_backdate_submit_rejects_band_item_belonging_to_another_user(session):
    user = await _make_returning_user(session, telegram_id=55009, days_ago=5)
    other = await UserRepository(session).create(telegram_id=55010, username="other")
    foreign_item = await EquipmentItemRepository(session).create(
        user_id=other.id, name="чужая резина", resistance_kg=None,
    )
    payload = {
        "performed_at": (datetime.now(UTC).date() - timedelta(days=2)).isoformat(),
        "block_a_working_reps": [11, 11, 11], "block_a_max_reps": 12,
        "block_b_working_reps": [4, 4, 4, 4], "block_b_max_reps": 4,
        "block_a_equipment_type": "band", "block_a_equipment_item_id": foreign_item.id,
        "block_b_equipment_type": "bodyweight",
        "comment": None, "confirm_anomalies": False,
    }
    response = await _post_backdate_raw(session, telegram_id=user.telegram_id, payload=payload)
    assert response.status_code == 400


async def test_backdate_submit_writes_workout_not_participating_in_cascade(session):
    user = await _make_returning_user(session, telegram_id=55011, days_ago=5)
    item = await EquipmentItemRepository(session).create(user_id=user.id, name="резина", resistance_kg=Decimal("12.0"))
    performed_at = datetime.now(UTC).date() - timedelta(days=2)

    payload = {
        "performed_at": performed_at.isoformat(),
        "block_a_working_reps": [11, 11, 11], "block_a_max_reps": 12,
        "block_b_working_reps": [4, 4, 4, 4], "block_b_max_reps": 4,
        "block_a_equipment_type": "band", "block_a_equipment_item_id": item.id,
        "block_b_equipment_type": "weight", "block_b_equipment_value": "10.0",
        "comment": "с телефона", "confirm_anomalies": False,
    }
    body = await _post_backdate(session, telegram_id=user.telegram_id, payload=payload)

    assert body["status"] == "ok"
    assert body["equipment_a"]["item_id"] == item.id
    assert Decimal(body["equipment_b"]["value"]) == Decimal("10.0")

    history = await WorkoutRepository(session).list_for_user(user.id)
    assert len(history) == 2
    backdated = next(w for w in history if w.performed_at.date() == performed_at)
    assert backdated.participates_in_cascade is False
    assert backdated.sequence_number is None
    assert backdated.comment == "с телефона"


async def test_backdate_submit_with_anomaly_requires_confirmation_and_does_not_write(session):
    user = await _make_returning_user(session, telegram_id=55012, days_ago=5)
    payload = {
        "performed_at": (datetime.now(UTC).date() - timedelta(days=2)).isoformat(),
        "block_a_working_reps": [60, 60, 60], "block_a_max_reps": 61,
        "block_b_working_reps": [4, 4, 4, 4], "block_b_max_reps": 4,
        "block_a_equipment_type": "bodyweight",
        "block_b_equipment_type": "bodyweight",
        "comment": None, "confirm_anomalies": False,
    }

    body = await _post_backdate(session, telegram_id=user.telegram_id, payload=payload)
    assert body["status"] == "anomaly_confirm_required"
    assert body["anomalies_a"]["large_value"] == 61
    history = await WorkoutRepository(session).list_for_user(user.id)
    assert len(history) == 1  # только исходная тренировка из _make_returning_user

    payload["confirm_anomalies"] = True
    body = await _post_backdate(session, telegram_id=user.telegram_id, payload=payload)
    assert body["status"] == "ok"
    history = await WorkoutRepository(session).list_for_user(user.id)
    assert len(history) == 2


async def test_backdate_submit_uses_same_service_as_direct_repository_call(session):
    """Доказательство "тот же сервис, не копия" (issue #52): результат HTTP
    POST /api/workout/backdate и результат прямого вызова
    WorkoutRepository.record_backdated_workout на идентичной истории должны
    совпасть по target_after."""
    user_web = await _make_returning_user(session, telegram_id=55013, days_ago=5)
    user_direct = await _make_returning_user(session, telegram_id=55014, days_ago=5)
    performed_at_date = datetime.now(UTC).date() - timedelta(days=2)

    payload = {
        "performed_at": performed_at_date.isoformat(),
        "block_a_working_reps": [11, 11, 11], "block_a_max_reps": 12,
        "block_b_working_reps": [4, 4, 4, 4], "block_b_max_reps": 4,
        "block_a_equipment_type": "bodyweight",
        "block_b_equipment_type": "bodyweight",
        "comment": None, "confirm_anomalies": False,
    }
    body = await _post_backdate(session, telegram_id=user_web.telegram_id, payload=payload)
    assert body["status"] == "ok"

    active_set = await WorkoutSetRepository(session).get_active_for_user(user_direct.id)
    performed_at = datetime(performed_at_date.year, performed_at_date.month, performed_at_date.day, tzinfo=UTC)
    direct_workout = await WorkoutRepository(session).record_backdated_workout(
        user_id=user_direct.id, workout_set_id=active_set.id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=4),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )
    direct_block_a = next(b for b in direct_workout.blocks if b.block_type == BlockType.A)
    direct_block_b = next(b for b in direct_workout.blocks if b.block_type == BlockType.B)
    assert body["target_a"] == direct_block_a.target_after
    assert body["target_b"] == direct_block_b.target_after
