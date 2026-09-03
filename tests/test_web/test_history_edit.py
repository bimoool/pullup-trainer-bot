"""GET/PATCH /api/history/{workout_id} — редактирование прошлой тренировки
в Mini App (issue #52): тонкая обвязка вокруг WorkoutRepository.edit_workout
(тот же каскадный пересчёт recalculate_cascade, что и
app.bot.handlers.workout_edit), не отдельная веб-копия.

test_patch_history_workout_uses_same_cascade_as_direct_repository_call —
то же доказательство "не копия логики", что уже используется в
test_workout.py: сравнение результата HTTP PATCH с прямым вызовом
WorkoutRepository.edit_workout на идентичной истории, включая эффект
каскада на следующую тренировку цепочки."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from app.db.models import BlockType, User, Workout
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
WEIGHT_VALUE = Decimal("10.0")


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


async def _get_history_detail_raw(session, telegram_id: int, workout_id: int):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get(f"/api/history/{workout_id}")
    finally:
        app.dependency_overrides.clear()


async def _patch_history_raw(session, telegram_id: int, workout_id: int, payload: dict):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.patch(f"/api/history/{workout_id}", json=payload)
    finally:
        app.dependency_overrides.clear()


async def _patch_history(session, telegram_id: int, workout_id: int, payload: dict) -> dict:
    response = await _patch_history_raw(session, telegram_id, workout_id, payload)
    assert response.status_code == 200
    return response.json()


async def _make_chain(session, *, telegram_id: int) -> tuple[User, list[Workout]]:
    """Пользователь с двумя тренировками подряд (сет ещё не закрыт) — блок A
    на резине, блок B на отягощении (нужен для проверки actual_weight ниже).
    Достаточный разрыв (5 дней), чтобы вторая тренировка не считалась
    "слишком рано" — тот же приём, что и в test_workout.py."""
    user = await UserRepository(session).create(telegram_id=telegram_id, username="tester")
    now = datetime.now(UTC)
    await SubscriptionService(session).start_trial(user.id, now=now)

    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=now - timedelta(days=20), reps=10,
    )
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    workouts = WorkoutRepository(session)

    first = await workouts.record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=now - timedelta(days=10),
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=WEIGHT_VALUE,
    )
    second = await workouts.record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=now - timedelta(days=5),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=WEIGHT_VALUE,
    )
    return user, [first, second]


# --- GET /api/history/{workout_id} ---------------------------------------------------


async def test_get_history_workout_for_unknown_telegram_id_is_404(session):
    user, workouts = await _make_chain(session, telegram_id=54001)
    response = await _get_history_detail_raw(session, telegram_id=99999, workout_id=workouts[0].id)
    assert response.status_code == 404


async def test_get_history_workout_for_foreign_workout_is_404(session):
    user, workouts = await _make_chain(session, telegram_id=54002)
    other = await UserRepository(session).create(telegram_id=54003, username="other")
    response = await _get_history_detail_raw(session, telegram_id=other.telegram_id, workout_id=workouts[0].id)
    assert response.status_code == 404


async def test_get_history_workout_returns_details_and_is_editable(session):
    user, workouts = await _make_chain(session, telegram_id=54004)
    response = await _get_history_detail_raw(session, telegram_id=user.telegram_id, workout_id=workouts[0].id)
    assert response.status_code == 200
    body = response.json()

    assert body["workout_id"] == workouts[0].id
    assert body["is_editable"] is True
    assert body["block_a"]["working_reps"] == [10, 10, 10]
    assert body["block_a"]["max_reps"] == 11
    assert body["block_a"]["equipment"]["type"] == "band"
    assert body["block_b"]["equipment"]["type"] == "weight"
    assert Decimal(body["block_b"]["equipment"]["value"]) == WEIGHT_VALUE


async def test_get_history_workout_marks_backdated_as_not_editable(session):
    user, _workouts = await _make_chain(session, telegram_id=54005)
    workout_set = (await WorkoutSetRepository(session).get_active_for_user(user.id))
    backdated = await WorkoutRepository(session).record_backdated_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC) - timedelta(days=3),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=WEIGHT_VALUE,
    )

    response = await _get_history_detail_raw(session, telegram_id=user.telegram_id, workout_id=backdated.id)
    assert response.status_code == 200
    assert response.json()["is_editable"] is False


# --- PATCH /api/history/{workout_id} -------------------------------------------------


async def test_patch_history_workout_rejects_non_editable_backdated_workout(session):
    user, _workouts = await _make_chain(session, telegram_id=54006)
    workout_set = (await WorkoutSetRepository(session).get_active_for_user(user.id))
    backdated = await WorkoutRepository(session).record_backdated_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC) - timedelta(days=3),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=WEIGHT_VALUE,
    )
    payload = {
        "block_a_working_reps": [12, 12, 12], "block_a_max_reps": 13,
        "block_b_working_reps": [4, 4, 4, 4], "block_b_max_reps": 4,
        "comment": None, "confirm_anomalies": False,
    }
    response = await _patch_history_raw(session, telegram_id=user.telegram_id, workout_id=backdated.id, payload=payload)
    assert response.status_code == 400


async def test_patch_history_workout_uses_same_cascade_as_direct_repository_call(session):
    user_web, workouts_web = await _make_chain(session, telegram_id=54007)
    user_direct, workouts_direct = await _make_chain(session, telegram_id=54008)

    payload = {
        "block_a_working_reps": [15, 15, 15], "block_a_max_reps": 16,
        "block_b_working_reps": [4, 4, 4, 4], "block_b_max_reps": 5,
        "comment": None, "confirm_anomalies": False,
    }
    body = await _patch_history(session, telegram_id=user_web.telegram_id, workout_id=workouts_web[0].id, payload=payload)
    assert body["status"] == "ok"

    direct_workout = await WorkoutRepository(session).edit_workout(
        workout_id=workouts_direct[0].id,
        block_a_reps=BlockLog(working_reps=(15, 15, 15), max_reps=16),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
    )
    direct_block_a = next(b for b in direct_workout.blocks if b.block_type == BlockType.A)
    direct_block_b = next(b for b in direct_workout.blocks if b.block_type == BlockType.B)
    assert body["target_a"] == direct_block_a.target_after
    assert body["target_b"] == direct_block_b.target_after

    # Каскад: вторая (более поздняя) тренировка цепочки должна пересчитаться
    # одинаково что через веб-эндпойнт, что через прямой вызов репозитория.
    web_second = await WorkoutRepository(session).get_by_id(workouts_web[1].id)
    direct_second = await WorkoutRepository(session).get_by_id(workouts_direct[1].id)
    web_second_a = next(b for b in web_second.blocks if b.block_type == BlockType.A)
    direct_second_a = next(b for b in direct_second.blocks if b.block_type == BlockType.A)
    assert web_second_a.target_before == direct_second_a.target_before
    assert web_second_a.target_after == direct_second_a.target_after


async def test_patch_history_workout_with_anomaly_requires_confirmation_and_does_not_write(session):
    user, workouts = await _make_chain(session, telegram_id=54009)
    payload = {
        "block_a_working_reps": [60, 60, 60], "block_a_max_reps": 61,
        "block_b_working_reps": [4, 4, 4, 4], "block_b_max_reps": 4,
        "comment": None, "confirm_anomalies": False,
    }

    body = await _patch_history(session, telegram_id=user.telegram_id, workout_id=workouts[0].id, payload=payload)
    assert body["status"] == "anomaly_confirm_required"
    assert body["anomalies_a"]["large_value"] == 61

    unchanged = await WorkoutRepository(session).get_by_id(workouts[0].id)
    unchanged_a = next(b for b in unchanged.blocks if b.block_type == BlockType.A)
    assert unchanged_a.working_reps == [10, 10, 10]

    payload["confirm_anomalies"] = True
    body = await _patch_history(session, telegram_id=user.telegram_id, workout_id=workouts[0].id, payload=payload)
    assert body["status"] == "ok"

    changed = await WorkoutRepository(session).get_by_id(workouts[0].id)
    changed_a = next(b for b in changed.blocks if b.block_type == BlockType.A)
    assert changed_a.working_reps == [60, 60, 60]


async def test_patch_history_workout_applies_actual_weight_override(session):
    user, workouts = await _make_chain(session, telegram_id=54010)
    payload = {
        "block_a_working_reps": [10, 10, 10], "block_a_max_reps": 11,
        "block_b_working_reps": [3, 3, 3, 3], "block_b_max_reps": 3,
        "block_b_actual_weight": "12.5",
        "comment": None, "confirm_anomalies": False,
    }
    body = await _patch_history(session, telegram_id=user.telegram_id, workout_id=workouts[0].id, payload=payload)
    assert body["status"] == "ok"
    assert Decimal(body["equipment_b"]["value"]) == Decimal("12.5")

    written = await WorkoutRepository(session).get_by_id(workouts[0].id)
    written_b = next(b for b in written.blocks if b.block_type == BlockType.B)
    assert written_b.equipment_value == Decimal("12.5")


async def test_patch_history_workout_applies_actual_band_item_override(session):
    user, workouts = await _make_chain(session, telegram_id=54011)
    item = await EquipmentItemRepository(session).create(user_id=user.id, name="моя резина", resistance_kg=None)

    payload = {
        "block_a_working_reps": [10, 10, 10], "block_a_max_reps": 11,
        "block_a_actual_band_item_id": item.id,
        "block_b_working_reps": [3, 3, 3, 3], "block_b_max_reps": 3,
        "comment": None, "confirm_anomalies": False,
    }
    body = await _patch_history(session, telegram_id=user.telegram_id, workout_id=workouts[0].id, payload=payload)
    assert body["status"] == "ok"
    assert body["equipment_a"]["item_id"] == item.id


async def test_patch_history_workout_rejects_band_item_belonging_to_another_user(session):
    user, workouts = await _make_chain(session, telegram_id=54012)
    other_user = await UserRepository(session).create(telegram_id=54013, username="other")
    foreign_item = await EquipmentItemRepository(session).create(
        user_id=other_user.id, name="чужая резина", resistance_kg=None,
    )

    payload = {
        "block_a_working_reps": [10, 10, 10], "block_a_max_reps": 11,
        "block_a_actual_band_item_id": foreign_item.id,
        "block_b_working_reps": [3, 3, 3, 3], "block_b_max_reps": 3,
        "comment": None, "confirm_anomalies": False,
    }
    response = await _patch_history_raw(session, telegram_id=user.telegram_id, workout_id=workouts[0].id, payload=payload)
    assert response.status_code == 400

    unchanged = await WorkoutRepository(session).get_by_id(workouts[0].id)
    unchanged_a = next(b for b in unchanged.blocks if b.block_type == BlockType.A)
    assert unchanged_a.working_reps == [10, 10, 10]
