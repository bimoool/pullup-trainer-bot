from datetime import UTC, datetime, timedelta

from app.db.models import Branch, Equipment, User
from app.db.repositories.achievements import AchievementRepository
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.events import EventRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.domain.constants import SET_LENGTH
from app.domain.session import BlockLog
from app.services.workout_log import WorkoutLogService

BAND = 22.0
WEIGHT = 10.0


async def _make_set(session, user: User) -> int:
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime(2025, 12, 1, tzinfo=UTC),
        branch_result=Branch.BAND, equipment_type=Equipment.BAND, reps=18,
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
        block_a_reps=BlockLog(working_reps=(15, 15, 15), max_reps=15),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        band_thickness_mm=BAND, weight_kg=WEIGHT,
    )

    events = await EventRepository(session).list_for_user(user.id)
    assert len(events) == 1
    assert events[0].event_type == "workout_completed"
    assert events[0].payload == {"workout_id": workout.id}


async def test_first_workout_unlocks_first_weighted_pullup(session, user: User):
    workout_set_id = await _make_set(session, user)
    service = WorkoutLogService(session)

    await service.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(15, 15, 15), max_reps=15),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        band_thickness_mm=BAND, weight_kg=WEIGHT,
    )

    assert await AchievementRepository(session).has_unlocked(user.id, "first_weighted_pullup") is True


async def test_second_workout_does_not_reunlock_first_weighted_pullup(session, user: User):
    workout_set_id = await _make_set(session, user)
    service = WorkoutLogService(session)

    for day in (1, 4):
        await service.record_workout(
            user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(day),
            block_a_reps=BlockLog(working_reps=(15, 15, 15), max_reps=15),
            block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
            band_thickness_mm=BAND, weight_kg=WEIGHT,
        )

    achievements = await AchievementRepository(session).list_for_user(user.id)
    assert [a.code for a in achievements].count("first_weighted_pullup") == 1


async def test_equipment_change_unlocks_band_changed(session, user: User):
    workout_set_id = await _make_set(session, user)
    service = WorkoutLogService(session)

    # target_before=18(base target after прошлого шага не задан, значит 15) —
    # берём числа, которые гарантированно переваливают за change_at(20)
    await service.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(1),
        block_a_reps=BlockLog(working_reps=(18, 18, 18), max_reps=21),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        band_thickness_mm=BAND, weight_kg=WEIGHT,
    )
    await service.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(4),
        block_a_reps=BlockLog(working_reps=(18, 18, 18), max_reps=21),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        band_thickness_mm=BAND, weight_kg=WEIGHT,
    )

    assert await AchievementRepository(session).has_unlocked(user.id, "band_changed") is True


async def test_completing_set_unlocks_set_completed(session, user: User):
    workout_set_id = await _make_set(session, user)
    service = WorkoutLogService(session)

    for day in range(1, SET_LENGTH + 1):
        await service.record_workout(
            user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(day * 3),
            block_a_reps=BlockLog(working_reps=(15, 15, 15), max_reps=15),
            block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
            band_thickness_mm=BAND, weight_kg=WEIGHT,
        )

    assert await AchievementRepository(session).has_unlocked(user.id, "set_completed") is True


async def test_workouts_before_set_length_do_not_unlock_set_completed(session, user: User):
    workout_set_id = await _make_set(session, user)
    service = WorkoutLogService(session)

    for day in range(1, SET_LENGTH):  # на одну меньше, чем нужно
        await service.record_workout(
            user_id=user.id, workout_set_id=workout_set_id, performed_at=_day(day * 3),
            block_a_reps=BlockLog(working_reps=(15, 15, 15), max_reps=15),
            block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
            band_thickness_mm=BAND, weight_kg=WEIGHT,
        )

    assert await AchievementRepository(session).has_unlocked(user.id, "set_completed") is False
