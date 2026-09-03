"""GET/PATCH /api/history/{workout_id} — редактирование прошлой
тренировки из Mini App (issue #52, волна 1): та же
WorkoutRepository.edit_workout (каскадный recalculate_cascade), что
app.bot.handlers.workout_edit вызывает в конце своего сценария, не
отдельная веб-копия. test_patch_edits_workout_and_cascades_later_workouts
сравнивает результат HTTP-запроса с прямым вызовом edit_workout на
идентичной истории — тот же приём доказательства "не дублированная
логика", что и tests/test_web/test_workout.py."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from app.db.models import BlockType
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
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


async def _get_entry_raw(session, telegram_id: int, workout_id: int):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get(f"/api/history/{workout_id}")
    finally:
        app.dependency_overrides.clear()


async def _patch_entry_raw(session, telegram_id: int, workout_id: int, payload: dict):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.patch(f"/api/history/{workout_id}", json=payload)
    finally:
        app.dependency_overrides.clear()


async def _make_user_with_workouts(session, *, telegram_id: int, count: int = 1):
    """count последовательных тренировок в цепочке каскада (record_workout,
    не бэкдейт) — та же forма данных, что использует
    tests/test_repositories/test_workouts_repository.py для проверки
    каскада."""
    user = await UserRepository(session).create(telegram_id=telegram_id, username="tester")
    now = datetime.now(UTC)
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=now - timedelta(days=30), reps=10,
    )
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)

    repo = WorkoutRepository(session)
    workouts = []
    for i in range(count):
        workout = await repo.record_workout(
            user_id=user.id, workout_set_id=workout_set.id, performed_at=now - timedelta(days=count - i),
            block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
            block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
            block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
            block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
        )
        workouts.append(workout)
    return user, workouts, workout_set


async def _make_backdated_workout(session, user_id: int, workout_set_id: int):
    return await WorkoutRepository(session).record_backdated_workout(
        user_id=user_id, workout_set_id=workout_set_id, performed_at=datetime.now(UTC) - timedelta(days=3),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )


def _edit_payload(**overrides) -> dict:
    payload = {
        "block_a_working_reps": [12, 12, 12], "block_a_max_reps": 13,
        "block_b_working_reps": [4, 4, 4, 4], "block_b_max_reps": 5,
        "comment": None, "confirm_anomalies": False,
    }
    payload.update(overrides)
    return payload


# --- GET /api/history/{id} -----------------------------------------------------------


async def test_get_entry_for_unknown_telegram_id_is_404(session):
    response = await _get_entry_raw(session, telegram_id=53001, workout_id=1)
    assert response.status_code == 404


async def test_get_entry_for_foreign_workout_is_404(session):
    _user, workouts, _workout_set = await _make_user_with_workouts(session, telegram_id=53002)
    other = await UserRepository(session).create(telegram_id=53003, username="other")
    response = await _get_entry_raw(session, telegram_id=other.telegram_id, workout_id=workouts[0].id)
    assert response.status_code == 404


async def test_get_entry_for_missing_workout_is_404(session):
    user, _workouts, _workout_set = await _make_user_with_workouts(session, telegram_id=53004)
    response = await _get_entry_raw(session, telegram_id=user.telegram_id, workout_id=999999)
    assert response.status_code == 404


async def test_get_entry_returns_editable_details(session):
    user, workouts, _workout_set = await _make_user_with_workouts(session, telegram_id=53005)
    response = await _get_entry_raw(session, telegram_id=user.telegram_id, workout_id=workouts[0].id)

    assert response.status_code == 200
    body = response.json()
    assert body["is_editable"] is True
    assert body["block_a"]["working_reps"] == [11, 11, 11]
    assert body["block_a"]["max_reps"] == 12
    assert body["block_a"]["equipment"]["type"] == "band"
    assert Decimal(body["block_a"]["equipment"]["value"]) == BAND_VALUE
    assert body["block_b"]["working_reps"] == [4, 4, 4, 4]


async def test_get_entry_reports_backdated_as_not_editable(session):
    user, _workouts, workout_set = await _make_user_with_workouts(session, telegram_id=53006)
    backdated = await _make_backdated_workout(session, user.id, workout_set.id)

    response = await _get_entry_raw(session, telegram_id=user.telegram_id, workout_id=backdated.id)
    assert response.status_code == 200
    assert response.json()["is_editable"] is False


# --- PATCH /api/history/{id} ---------------------------------------------------------


async def test_patch_for_unknown_telegram_id_reports_not_found_status(session):
    response = await _patch_entry_raw(session, telegram_id=53007, workout_id=1, payload=_edit_payload())
    assert response.status_code == 200
    assert response.json()["status"] == "not_found"


async def test_patch_for_foreign_workout_reports_not_found_status(session):
    _user, workouts, _workout_set = await _make_user_with_workouts(session, telegram_id=53008)
    other = await UserRepository(session).create(telegram_id=53009, username="other")

    response = await _patch_entry_raw(
        session, telegram_id=other.telegram_id, workout_id=workouts[0].id, payload=_edit_payload(),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "not_found"


async def test_patch_rejects_backdated_workout(session):
    user, _workouts, workout_set = await _make_user_with_workouts(session, telegram_id=53010)
    backdated = await _make_backdated_workout(session, user.id, workout_set.id)

    response = await _patch_entry_raw(
        session, telegram_id=user.telegram_id, workout_id=backdated.id, payload=_edit_payload(),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "not_editable"


async def test_patch_edits_workout_and_cascades_later_workouts(session):
    user_web, workouts_web, _set_web = await _make_user_with_workouts(session, telegram_id=53011, count=2)
    _user_direct, workouts_direct, _set_direct = await _make_user_with_workouts(session, telegram_id=53012, count=2)

    original_second_target_before = next(
        b for b in workouts_web[1].blocks if b.block_type == BlockType.A
    ).target_before

    payload = _edit_payload(block_a_working_reps=[13, 13, 13], block_a_max_reps=14)
    response = await _patch_entry_raw(
        session, telegram_id=user_web.telegram_id, workout_id=workouts_web[0].id, payload=payload,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"

    direct_edited = await WorkoutRepository(session).edit_workout(
        workout_id=workouts_direct[0].id,
        block_a_reps=BlockLog(working_reps=(13, 13, 13), max_reps=14),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
    )
    direct_block_a = next(b for b in direct_edited.blocks if b.block_type == BlockType.A)
    assert body["target_a"] == direct_block_a.target_after

    web_second = await WorkoutRepository(session).get_by_id(workouts_web[1].id)
    direct_second = await WorkoutRepository(session).get_by_id(workouts_direct[1].id)
    web_second_block_a = next(b for b in web_second.blocks if b.block_type == BlockType.A)
    direct_second_block_a = next(b for b in direct_second.blocks if b.block_type == BlockType.A)

    # Каскад реально пересчитал вторую тренировку (не просто совпал по
    # случайности с тем, что уже было) — target_before сдвинулся от
    # исходного значения, посчитанного до правки.
    assert web_second_block_a.target_before != original_second_target_before
    assert web_second_block_a.target_before == direct_second_block_a.target_before


async def test_patch_with_anomaly_requires_confirmation_and_does_not_write(session):
    user, workouts, _workout_set = await _make_user_with_workouts(session, telegram_id=53013)
    payload = _edit_payload(block_a_working_reps=[60, 60, 60], block_a_max_reps=61)

    response = await _patch_entry_raw(
        session, telegram_id=user.telegram_id, workout_id=workouts[0].id, payload=payload,
    )
    body = response.json()
    assert body["status"] == "anomaly_confirm_required"
    assert body["anomalies_a"]["large_value"] == 61

    unchanged = await WorkoutRepository(session).get_by_id(workouts[0].id)
    unchanged_block_a = next(b for b in unchanged.blocks if b.block_type == BlockType.A)
    assert unchanged_block_a.working_reps == [11, 11, 11]

    payload["confirm_anomalies"] = True
    response = await _patch_entry_raw(
        session, telegram_id=user.telegram_id, workout_id=workouts[0].id, payload=payload,
    )
    assert response.json()["status"] == "ok"

    changed = await WorkoutRepository(session).get_by_id(workouts[0].id)
    changed_block_a = next(b for b in changed.blocks if b.block_type == BlockType.A)
    assert changed_block_a.working_reps == [60, 60, 60]


async def test_patch_applies_actual_weight_override_for_weight_block(session):
    user = await UserRepository(session).create(telegram_id=53014, username="weighted")
    now = datetime.now(UTC)
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=now - timedelta(days=10), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    workout = await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=now,
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=Decimal("10.0"),
    )

    payload = _edit_payload(block_b_actual_weight="12.5")
    response = await _patch_entry_raw(session, telegram_id=user.telegram_id, workout_id=workout.id, payload=payload)
    body = response.json()

    assert body["status"] == "ok"
    assert Decimal(body["equipment_b"]["value"]) == Decimal("12.5")

    updated = await WorkoutRepository(session).get_by_id(workout.id)
    updated_block_b = next(b for b in updated.blocks if b.block_type == BlockType.B)
    assert updated_block_b.equipment_value == Decimal("12.5")
