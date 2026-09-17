"""DELETE /api/history/{workout_id} (issue #146) — удаление тренировок,
внесённых не в цепочку каскада (бэкдейт/свободные). Обычные тренировки
цепочки удалению не подлежат (решение о пересчёте каскада не согласовано,
см. app/services/workout_deletion.py)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.main import app
from tests.test_web.test_history_edit import _FakeInitData, _FakeWebAppUser, _make_chain

BAND_VALUE = Decimal("15.0")
WEIGHT_VALUE = Decimal("10.0")


def _override_dependencies(session, telegram_id: int) -> None:
    app.dependency_overrides[get_validated_init_data] = (
        lambda: _FakeInitData(user=_FakeWebAppUser(id=telegram_id, first_name="Тест"))
    )

    async def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session


async def _delete_history_raw(session, telegram_id: int, workout_id: int):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.delete(f"/api/history/{workout_id}")
    finally:
        app.dependency_overrides.clear()


async def _get_history_list_raw(session, telegram_id: int):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get("/api/history")
    finally:
        app.dependency_overrides.clear()


async def test_history_entry_marks_backdated_as_deletable_and_cascade_as_not(session):
    user, workouts = await _make_chain(session, telegram_id=60001)
    workout_set = await WorkoutSetRepository(session).get_active_for_user(user.id)
    await WorkoutRepository(session).record_backdated_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC) - timedelta(days=3),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=WEIGHT_VALUE,
    )

    response = await _get_history_list_raw(session, telegram_id=user.telegram_id)
    assert response.status_code == 200
    items = {item["workout_id"]: item for item in response.json()["items"]}
    assert items[workouts[0].id]["is_deletable"] is False
    backdated_id = next(iter(set(items) - {w.id for w in workouts}))
    assert items[backdated_id]["is_deletable"] is True


async def test_delete_history_workout_for_unknown_telegram_id_is_404(session):
    _user, workouts = await _make_chain(session, telegram_id=60002)
    response = await _delete_history_raw(session, telegram_id=99999, workout_id=workouts[0].id)
    assert response.status_code == 404


async def test_delete_history_workout_for_foreign_workout_is_404(session):
    _user, workouts = await _make_chain(session, telegram_id=60003)
    other = await UserRepository(session).create(telegram_id=60004, username="other")
    response = await _delete_history_raw(session, telegram_id=other.telegram_id, workout_id=workouts[0].id)
    assert response.status_code == 404


async def test_delete_history_workout_rejects_cascade_workout(session):
    user, workouts = await _make_chain(session, telegram_id=60005)
    response = await _delete_history_raw(session, telegram_id=user.telegram_id, workout_id=workouts[0].id)
    assert response.status_code == 400

    still_there = await WorkoutRepository(session).get_by_id(workouts[0].id)
    assert still_there is not None


async def test_delete_history_workout_removes_backdated_entry_and_archives_it(session):
    user, _workouts = await _make_chain(session, telegram_id=60006)
    workout_set = await WorkoutSetRepository(session).get_active_for_user(user.id)
    completed_before = workout_set.workouts_completed
    backdated = await WorkoutRepository(session).record_backdated_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC) - timedelta(days=3),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=WEIGHT_VALUE,
    )
    await session.refresh(workout_set)
    assert workout_set.workouts_completed == completed_before + 1

    response = await _delete_history_raw(session, telegram_id=user.telegram_id, workout_id=backdated.id)
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    assert await WorkoutRepository(session).get_by_id(backdated.id) is None

    archived_workouts = (
        await session.execute(
            text("SELECT count(*) FROM workouts_archive_admin_reset WHERE id = :wid"), {"wid": backdated.id},
        )
    ).scalar()
    assert archived_workouts == 1
    archived_blocks = (
        await session.execute(
            text("SELECT count(*) FROM blocks_archive_admin_reset WHERE workout_id = :wid"), {"wid": backdated.id},
        )
    ).scalar()
    assert archived_blocks == 2

    # record_backdated_workout инкрементировал workouts_completed при
    # создании — удаление обязано откатить это (issue #146), иначе чётность
    # is_heavy (issue #97) для всех последующих тренировок блока Б навсегда
    # сдвинется на единицу.
    await session.refresh(workout_set)
    assert workout_set.workouts_completed == completed_before


async def test_delete_history_workout_removes_free_entry_without_touching_workout_set(session):
    user, _workouts = await _make_chain(session, telegram_id=60007)
    workout_set = await WorkoutSetRepository(session).get_active_for_user(user.id)
    completed_before = workout_set.workouts_completed
    free_entry = await WorkoutRepository(session).record_free_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC) - timedelta(days=1),
        block_a_reps=BlockLog(working_reps=(20,), max_reps=25),
        equipment_type=EquipmentType.BODYWEIGHT,
    )

    response = await _delete_history_raw(session, telegram_id=user.telegram_id, workout_id=free_entry.id)
    assert response.status_code == 200

    assert await WorkoutRepository(session).get_by_id(free_entry.id) is None
    await session.refresh(workout_set)
    assert workout_set.workouts_completed == completed_before


async def test_delete_history_workout_is_404_on_second_call(session):
    user, _workouts = await _make_chain(session, telegram_id=60008)
    workout_set = await WorkoutSetRepository(session).get_active_for_user(user.id)
    backdated = await WorkoutRepository(session).record_backdated_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC) - timedelta(days=3),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=WEIGHT_VALUE,
    )

    first = await _delete_history_raw(session, telegram_id=user.telegram_id, workout_id=backdated.id)
    assert first.status_code == 200
    second = await _delete_history_raw(session, telegram_id=user.telegram_id, workout_id=backdated.id)
    assert second.status_code == 404
