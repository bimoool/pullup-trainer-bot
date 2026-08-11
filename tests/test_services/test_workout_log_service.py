from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db.models import EquipmentType, User
from app.db.repositories.achievements import AchievementRepository
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.events import EventRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.domain.constants import SET_LENGTH
from app.domain.session import BlockLog
from app.services.workout_log import WorkoutLogService

BAND_VALUE = Decimal("22.0")
WEIGHT_VALUE = Decimal("10.0")


async def _make_set(session, user: User) -> int:
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime(2025, 12, 1, tzinfo=UTC), reps=8,
    )
    workout_set = await WorkoutSetRepository(session).create(
        user_id=user.id, started_from_baseline_id=baseline.id,
    )
    return workout_set.id


def _day(n: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=n)


async def test_record_workout_logs_event(session, user: User):
    workout_set_id = await _make_set(session, user)
    service = WorkoutLogService(session)

    workout = await service.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )

    events = await EventRepository(session).list_for_user(user.id)
    assert len(events) == 1
    assert events[0].event_type == "workout_completed"
    assert events[0].payload == {"workout_id": workout.id}


async def test_backdated_workout_logs_separate_event_type(session, user: User):
    workout_set_id = await _make_set(session, user)
    service = WorkoutLogService(session)

    workout = await service.record_backdated_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )

    events = await EventRepository(session).list_for_user(user.id)
    assert len(events) == 1
    assert events[0].event_type == "workout_backdated"
    assert events[0].payload == {"workout_id": workout.id}


async def test_first_workout_on_weight_unlocks_first_weighted_pullup(session, user: User):
    workout_set_id = await _make_set(session, user)
    service = WorkoutLogService(session)

    await service.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=WEIGHT_VALUE,
    )

    assert await AchievementRepository(session).has_unlocked(user.id, "first_weighted_pullup") is True
    # Часть 10: сумма за "Первое подтягивание с отягощением" утверждена — 100 монет.
    reloaded = await UserRepository(session).get_by_id(user.id)
    assert reloaded.coins_balance == 100


async def test_second_weighted_workout_does_not_reunlock(session, user: User):
    workout_set_id = await _make_set(session, user)
    service = WorkoutLogService(session)

    for day in (1, 4):
        await service.record_workout(
            user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(day),
            block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=11),
            block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
            block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
            block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=WEIGHT_VALUE,
        )

    achievements = await AchievementRepository(session).list_for_user(user.id)
    assert [a.code for a in achievements].count("first_weighted_pullup") == 1


async def test_equipment_threshold_hit_unlocks_equipment_changed(session, user: User):
    """Новый механизм: порог сравнивается с сырыми рабочими подходами сразу
    на первой тренировке — не нужно двух вызовов, как было раньше со
    сравнением расчётной цели."""
    workout_set_id = await _make_set(session, user)
    service = WorkoutLogService(session)

    await service.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(20, 20, 20), max_reps=21),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )

    assert await AchievementRepository(session).has_unlocked(user.id, "equipment_changed") is True


async def test_completing_set_unlocks_set_completed(session, user: User):
    workout_set_id = await _make_set(session, user)
    service = WorkoutLogService(session)

    for day in range(1, SET_LENGTH + 1):
        await service.record_workout(
            user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(day * 3),
            block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=11),
            block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
            block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
            block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
        )

    assert await AchievementRepository(session).has_unlocked(user.id, "set_completed") is True


async def test_workouts_before_set_length_do_not_unlock_set_completed(session, user: User):
    workout_set_id = await _make_set(session, user)
    service = WorkoutLogService(session)

    for day in range(1, SET_LENGTH):  # на одну меньше, чем нужно
        await service.record_workout(
            user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(day * 3),
            block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=11),
            block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
            block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
            block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
        )

    assert await AchievementRepository(session).has_unlocked(user.id, "set_completed") is False
