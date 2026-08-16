from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db.models import EquipmentType, User
from app.db.repositories.achievements import AchievementRepository
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.elective_workouts import ElectiveWorkoutRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.electives import ElectiveType
from app.domain.session import BlockLog
from app.services.achievement_checks import unlock_history_achievements, unlock_volume_milestones
from app.services.workout_log import WorkoutLogService

BAND_VALUE = Decimal("22.0")
NOW = datetime(2026, 3, 1, tzinfo=UTC)


async def _make_set(session, user: User, *, baseline_reps: int = 8) -> int:
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime(2025, 12, 1, tzinfo=UTC), reps=baseline_reps,
    )
    workout_set = await WorkoutSetRepository(session).create(
        user_id=user.id, started_from_baseline_id=baseline.id,
    )
    return workout_set.id


async def _record(service: WorkoutLogService, *, user: User, workout_set_id: int, day: int, max_reps: int = 11):
    return await service.record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=NOW - timedelta(days=day),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=max_reps),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )


async def test_unlock_history_achievements_no_workouts_is_noop(session, user: User):
    await unlock_history_achievements(session, user.id, now=NOW)
    assert await AchievementRepository(session).list_for_user(user.id) == []


async def test_ten_workouts_streak_unlocks_via_workout_log_service(session, user: User):
    workout_set_id = await _make_set(session, user)
    service = WorkoutLogService(session)

    # 10 тренировок, шаг 3 дня — далеко от GAP_ROLLBACK_DAYS(21), без пропуска
    for day in range(27, -1, -3):
        await _record(service, user=user, workout_set_id=workout_set_id, day=day)

    assert await AchievementRepository(session).has_unlocked(user.id, "ten_workouts_streak") is True
    reloaded = await UserRepository(session).get_by_id(user.id)
    assert reloaded.coins_balance >= 100  # +100 за стрик, могут быть другие ачивки в сумме


async def test_month_no_gaps_unlocks_via_workout_log_service(session, user: User):
    # unlock_history_achievements вызывается напрямую с фиксированным now:
    # WorkoutLogService сам берёт datetime.now(UTC) (реальное время), а
    # тестовые даты тренировок привязаны к фиксированному NOW — через
    # сервис этот сценарий непроверяем (окно "последние 30 дней" от
    # РЕАЛЬНОГО текущего момента не совпадёт с фиксированными датами).
    workout_set_id = await _make_set(session, user)
    workouts = WorkoutRepository(session)
    for day in range(28, -1, -4):
        await workouts.record_workout(
            user_id=user.id, workout_set_id=workout_set_id, performed_at=NOW - timedelta(days=day),
            block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=11),
            block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
            block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
            block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
        )

    await unlock_history_achievements(session, user.id, now=NOW)

    assert await AchievementRepository(session).has_unlocked(user.id, "month_no_gaps") is True


async def test_month_no_gaps_not_unlocked_with_large_gap(session, user: User):
    workout_set_id = await _make_set(session, user)
    workouts = WorkoutRepository(session)
    for day in (29, 0):  # разрыв 29 дней >= GAP_ROLLBACK_DAYS(21)
        await workouts.record_workout(
            user_id=user.id, workout_set_id=workout_set_id, performed_at=NOW - timedelta(days=day),
            block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=11),
            block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
            block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
            block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
        )

    await unlock_history_achievements(session, user.id, now=NOW)

    assert await AchievementRepository(session).has_unlocked(user.id, "month_no_gaps") is False


async def test_max_reps_plus_ten_unlocks_from_best_block_across_history(session, user: User):
    workout_set_id = await _make_set(session, user, baseline_reps=10)
    service = WorkoutLogService(session)

    await _record(service, user=user, workout_set_id=workout_set_id, day=5, max_reps=12)
    await _record(service, user=user, workout_set_id=workout_set_id, day=1, max_reps=21)  # 10 + 11

    assert await AchievementRepository(session).has_unlocked(user.id, "max_reps_plus_ten") is True


async def test_max_reps_plus_ten_not_unlocked_below_threshold(session, user: User):
    workout_set_id = await _make_set(session, user, baseline_reps=10)
    service = WorkoutLogService(session)

    await _record(service, user=user, workout_set_id=workout_set_id, day=1, max_reps=19)  # +9, не хватает

    assert await AchievementRepository(session).has_unlocked(user.id, "max_reps_plus_ten") is False


async def test_backdated_and_free_workouts_also_check_history_achievements(session, user: User):
    """record_backdated_workout/record_free_workout не участвуют в
    каскаде, но серия/пропуски/максимум от каскада не зависят — должны
    проверяться и там (в отличие от EQUIPMENT_CHANGED/SET_COMPLETED)."""
    workout_set_id = await _make_set(session, user, baseline_reps=10)
    service = WorkoutLogService(session)

    for day in range(27, -1, -3):
        await service.record_backdated_workout(
            user_id=user.id, workout_set_id=workout_set_id, performed_at=NOW - timedelta(days=day),
            block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=11),
            block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
            block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
            block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
        )

    assert await AchievementRepository(session).has_unlocked(user.id, "ten_workouts_streak") is True


async def test_backdated_workout_does_not_unlock_equipment_changed_or_set_completed(session, user: User):
    workout_set_id = await _make_set(session, user)
    service = WorkoutLogService(session)

    await service.record_backdated_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=NOW,
        block_a_reps=BlockLog(working_reps=(20, 20, 20), max_reps=21),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )

    assert await AchievementRepository(session).has_unlocked(user.id, "equipment_changed") is False
    assert await AchievementRepository(session).has_unlocked(user.id, "set_completed") is False


async def test_volume_milestone_unlocks_via_workout_log_service(session, user: User):
    workout_set_id = await _make_set(session, user)
    service = WorkoutLogService(session)

    # объёмный блок 33 + силовой 12 = 45 за тренировку, нужно >=100 суммарно
    await _record(service, user=user, workout_set_id=workout_set_id, day=2)
    await _record(service, user=user, workout_set_id=workout_set_id, day=1)
    await _record(service, user=user, workout_set_id=workout_set_id, day=0)

    assert await AchievementRepository(session).has_unlocked(user.id, "volume_100") is True
    reloaded = await UserRepository(session).get_by_id(user.id)
    assert reloaded.coins_balance >= 20


async def test_volume_milestone_not_unlocked_below_threshold(session, user: User):
    workout_set_id = await _make_set(session, user)
    service = WorkoutLogService(session)

    await _record(service, user=user, workout_set_id=workout_set_id, day=0)

    assert await AchievementRepository(session).has_unlocked(user.id, "volume_100") is False


async def test_volume_milestone_includes_electives(session, user: User):
    """Ключевая проверка расхождения с all_cycles_analytics: факультативы
    ДОЛЖНЫ учитываться в пороге объёма для ачивок, хотя в "Аналитике по
    всем циклам" их нет."""
    await ElectiveWorkoutRepository(session).create(
        user_id=user.id, elective_type=ElectiveType.VOLUME_TARGET, performed_at=NOW,
        total_reps=150, reps_sequence=None, equipment_type=EquipmentType.BODYWEIGHT,
    )

    await unlock_volume_milestones(session, user.id)

    assert await AchievementRepository(session).has_unlocked(user.id, "volume_100") is True


async def test_volume_milestone_multiple_thresholds_from_backfill_style_jump(session, user: User):
    await ElectiveWorkoutRepository(session).create(
        user_id=user.id, elective_type=ElectiveType.VOLUME_TARGET, performed_at=NOW,
        total_reps=1500, reps_sequence=None, equipment_type=EquipmentType.BODYWEIGHT,
    )

    await unlock_volume_milestones(session, user.id)

    achievements = {a.code for a in await AchievementRepository(session).list_for_user(user.id)}
    assert {"volume_100", "volume_1000"} <= achievements
    assert "volume_10000" not in achievements
