"""GET /api/free-workout/plan + POST /api/free-workout/submit (issue #109) —
перенос в Mini App "➕ Внести свободные подтягивания" бота
(app/bot/handlers/free_workout.py), тот же WorkoutLogService.record_free_workout,
не отдельная копия. Снаряд здесь ВСЕГДА явный выбор (тот же принцип, что у
бэкдейта, issue #52) — свободный вход вне цикла программы, наследовать
target/work_sets/снаряд из resolve_next_targets не от чего.

Нет проверки подписки (как и у бота — handle_free_workout_start не вызывает
SubscriptionService) и нет статуса "needs_first_workout" (в отличие от
факультатива) — единственная реальная зависимость: активный WorkoutSet
(baseline уже пройден)."""

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


async def _get_free_workout_plan(session, telegram_id: int) -> dict:
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/free-workout/plan")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    return response.json()


async def _post_free_workout_raw(session, telegram_id: int, payload: dict):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/free-workout/submit", json=payload)
    finally:
        app.dependency_overrides.clear()


async def _post_free_workout(session, telegram_id: int, payload: dict) -> dict:
    response = await _post_free_workout_raw(session, telegram_id, payload)
    assert response.status_code == 200
    return response.json()


async def _make_user_with_baseline(session, *, telegram_id: int) -> int:
    """Онбордился (есть baseline) — этого достаточно для активного
    WorkoutSet и, следовательно, для свободных подтягиваний, без единой
    структурированной тренировки. Без SubscriptionService.start_trial
    намеренно — свободные подтягивания не за паивеллом (см. докстринг
    модуля)."""
    user = await UserRepository(session).create(telegram_id=telegram_id, username="tester")
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    return user.id


# --- GET /api/free-workout/plan ------------------------------------------------------


async def test_free_workout_plan_for_unknown_telegram_id_is_not_onboarded(session):
    body = await _get_free_workout_plan(session, telegram_id=56001)
    assert body["status"] == "not_onboarded"


async def test_free_workout_plan_without_baseline_is_no_active_set(session):
    user = await UserRepository(session).create(telegram_id=56002, username="nobaseline")
    body = await _get_free_workout_plan(session, telegram_id=user.telegram_id)
    assert body["status"] == "no_active_set"


async def test_free_workout_plan_does_not_require_subscription(session):
    """В отличие от обычной тренировки (see test_workout.py::
    test_plan_no_access_without_subscription), свободные подтягивания
    доступны и без подписки — тот же принцип, что и у факультатива."""
    telegram_id = 56003
    await _make_user_with_baseline(session, telegram_id=telegram_id)
    body = await _get_free_workout_plan(session, telegram_id=telegram_id)
    assert body["status"] == "ready"


async def test_free_workout_plan_ready_includes_workout_set_id_and_band_items(session):
    telegram_id = 56004
    user_id = await _make_user_with_baseline(session, telegram_id=telegram_id)
    item = await EquipmentItemRepository(session).create(user_id=user_id, name="резина", resistance_kg=Decimal("10.0"))

    body = await _get_free_workout_plan(session, telegram_id=telegram_id)

    assert body["status"] == "ready"
    assert body["workout_set_id"] is not None
    assert body["band_items"] == [{"id": item.id, "name": "резина", "resistance_kg": "10.0"}]


# --- POST /api/free-workout/submit ---------------------------------------------------


async def test_free_workout_submit_for_unknown_telegram_id_reports_status_without_writing(session):
    payload = {
        "working_reps": [10, 8, 6], "max_reps": 5,
        "equipment_type": "bodyweight", "comment": None, "confirm_anomalies": False,
    }
    body = await _post_free_workout(session, telegram_id=99997, payload=payload)
    assert body["status"] == "not_onboarded"


async def test_free_workout_submit_requires_weight_value_for_weight_type(session):
    telegram_id = 56005
    await _make_user_with_baseline(session, telegram_id=telegram_id)
    payload = {
        "working_reps": [10, 8, 6], "max_reps": 5,
        "equipment_type": "weight", "comment": None, "confirm_anomalies": False,
    }
    response = await _post_free_workout_raw(session, telegram_id=telegram_id, payload=payload)
    assert response.status_code == 400


async def test_free_workout_submit_requires_valid_band_item_for_band_type(session):
    telegram_id = 56006
    await _make_user_with_baseline(session, telegram_id=telegram_id)
    payload = {
        "working_reps": [10, 8, 6], "max_reps": 5,
        "equipment_type": "band", "comment": None, "confirm_anomalies": False,
    }
    response = await _post_free_workout_raw(session, telegram_id=telegram_id, payload=payload)
    assert response.status_code == 400


async def test_free_workout_submit_rejects_band_item_belonging_to_another_user(session):
    telegram_id = 56007
    user_id = await _make_user_with_baseline(session, telegram_id=telegram_id)
    other_id = await _make_user_with_baseline(session, telegram_id=56008)
    foreign_item = await EquipmentItemRepository(session).create(
        user_id=other_id, name="чужая резина", resistance_kg=None,
    )
    payload = {
        "working_reps": [10, 8, 6], "max_reps": 5,
        "equipment_type": "band", "equipment_item_id": foreign_item.id,
        "comment": None, "confirm_anomalies": False,
    }
    response = await _post_free_workout_raw(session, telegram_id=telegram_id, payload=payload)
    assert response.status_code == 400
    assert user_id  # только чтобы не остался неиспользуемым


async def test_free_workout_submit_writes_free_entry_outside_cascade_and_set(session):
    telegram_id = 56009
    user_id = await _make_user_with_baseline(session, telegram_id=telegram_id)
    payload = {
        "working_reps": [10, 8, 6], "max_reps": 5,
        "equipment_type": "bodyweight", "comment": "в парке", "confirm_anomalies": False,
    }
    body = await _post_free_workout(session, telegram_id=telegram_id, payload=payload)

    assert body["status"] == "ok"
    assert body["result_text"] == "10, 8, 6, максимум 5"
    assert body["equipment"]["type"] == "bodyweight"

    history = await WorkoutRepository(session).list_for_user(user_id)
    assert len(history) == 1
    workout = history[0]
    assert workout.is_free_entry is True
    assert workout.participates_in_cascade is False
    assert workout.sequence_number is None
    assert workout.comment == "в парке"

    # Сет из 12 не продвинулся — свободные подтягивания в него не входят
    # (см. докстринг WorkoutRepository.record_free_workout).
    active_set = await WorkoutSetRepository(session).get_active_for_user(user_id)
    assert active_set.workouts_completed == 0


async def test_free_workout_submit_with_band_item(session):
    telegram_id = 56010
    user_id = await _make_user_with_baseline(session, telegram_id=telegram_id)
    item = await EquipmentItemRepository(session).create(user_id=user_id, name="резина", resistance_kg=Decimal("12.0"))
    payload = {
        "working_reps": [10, 8], "max_reps": 6,
        "equipment_type": "band", "equipment_item_id": item.id,
        "comment": None, "confirm_anomalies": False,
    }
    body = await _post_free_workout(session, telegram_id=telegram_id, payload=payload)
    assert body["status"] == "ok"
    assert body["equipment"]["item_id"] == item.id


async def test_free_workout_submit_with_anomaly_requires_confirmation_and_does_not_write(session):
    telegram_id = 56011
    user_id = await _make_user_with_baseline(session, telegram_id=telegram_id)
    payload = {
        "working_reps": [60, 60, 60], "max_reps": 61,
        "equipment_type": "bodyweight", "comment": None, "confirm_anomalies": False,
    }

    body = await _post_free_workout(session, telegram_id=telegram_id, payload=payload)
    assert body["status"] == "anomaly_confirm_required"
    assert body["anomalies"]["large_value"] == 61
    history = await WorkoutRepository(session).list_for_user(user_id)
    assert len(history) == 0

    payload["confirm_anomalies"] = True
    body = await _post_free_workout(session, telegram_id=telegram_id, payload=payload)
    assert body["status"] == "ok"
    history = await WorkoutRepository(session).list_for_user(user_id)
    assert len(history) == 1


async def test_free_workout_submit_uses_same_service_as_direct_repository_call(session):
    """Доказательство "тот же сервис, не копия" (issue #109, тот же принцип,
    что test_backdate_submit_uses_same_service_as_direct_repository_call):
    результат HTTP POST /api/free-workout/submit и прямой вызов
    WorkoutRepository.record_free_workout на идентичном вводе должны дать
    одинаковый результат."""
    telegram_id_web = 56012
    user_id_web = await _make_user_with_baseline(session, telegram_id=telegram_id_web)
    user_id_direct = await _make_user_with_baseline(session, telegram_id=56013)

    payload = {
        "working_reps": [10, 8, 6], "max_reps": 5,
        "equipment_type": "bodyweight", "comment": None, "confirm_anomalies": False,
    }
    body = await _post_free_workout(session, telegram_id=telegram_id_web, payload=payload)
    assert body["status"] == "ok"

    active_set = await WorkoutSetRepository(session).get_active_for_user(user_id_direct)
    direct_workout = await WorkoutRepository(session).record_free_workout(
        user_id=user_id_direct, workout_set_id=active_set.id, performed_at=datetime.now(UTC),
        block_a_reps=BlockLog(working_reps=(10, 8, 6), max_reps=5),
        equipment_type=EquipmentType.BODYWEIGHT,
    )

    web_workout = (await WorkoutRepository(session).list_for_user(user_id_web))[0]
    assert web_workout.blocks[0].max_reps == direct_workout.blocks[0].max_reps
    assert [b.working_reps for b in web_workout.blocks] == [b.working_reps for b in direct_workout.blocks]


async def test_free_workout_plan_no_active_set_after_deep_gap_still_ready(session):
    """Свободные подтягивания не гейтуются gap_retest_required/too_early
    (та же причина, что у бэкдейта) — большой перерыв с прошлой
    структурированной тренировки не блокирует форму."""
    telegram_id = 56014
    user_id = await _make_user_with_baseline(session, telegram_id=telegram_id)
    active_set = await WorkoutSetRepository(session).get_active_for_user(user_id)
    await WorkoutRepository(session).record_workout(
        user_id=user_id, workout_set_id=active_set.id, performed_at=datetime.now(UTC) - timedelta(days=40),
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )

    body = await _get_free_workout_plan(session, telegram_id=telegram_id)
    assert body["status"] == "ready"
