from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db.models import EquipmentType, User
from app.db.repositories.achievements import AchievementRepository
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.session import BlockLog
from app.services.workout_log import WorkoutLogService
from scripts.backfill_achievements import backfill_all_users

BAND_VALUE = Decimal("22.0")
NOW = datetime(2026, 3, 1, tzinfo=UTC)


async def test_backfill_unlocks_streak_for_existing_unbroken_history(session, user: User):
    """Тот самый реальный кейс из прода (user_id=2, 15 тренировок подряд
    без пропуска) — TEN_WORKOUTS_STREAK при == 10 никогда бы не сработал,
    бэкфилл должен разблокировать его по накопленной истории."""
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime(2025, 12, 1, tzinfo=UTC), reps=8,
    )
    workout_set = await WorkoutSetRepository(session).create(
        user_id=user.id, started_from_baseline_id=baseline.id,
    )

    # Записываем историю НАПРЯМУЮ через WorkoutRepository, минуя
    # WorkoutLogService (чтобы ачивки НЕ разблокировались по ходу записи —
    # имитируем "историю, накопленную до появления этой ачивки").
    workouts = WorkoutRepository(session)
    for day in range(42, -1, -3):  # 15 тренировок, шаг 3 дня
        await workouts.record_workout(
            user_id=user.id, workout_set_id=workout_set.id, performed_at=NOW - timedelta(days=day),
            block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=11),
            block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
            block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
            block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
        )

    assert await AchievementRepository(session).has_unlocked(user.id, "ten_workouts_streak") is False

    checked = await backfill_all_users(session, now=NOW)

    assert checked == 1
    assert await AchievementRepository(session).has_unlocked(user.id, "ten_workouts_streak") is True


async def test_backfill_is_idempotent_on_second_run(session, user: User):
    workout_set_id_baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime(2025, 12, 1, tzinfo=UTC), reps=10,
    )
    workout_set = await WorkoutSetRepository(session).create(
        user_id=user.id, started_from_baseline_id=workout_set_id_baseline.id,
    )
    service = WorkoutLogService(session)
    await service.record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=NOW,
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=25),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    balance_after_first_event = (await UserRepository(session).get_by_id(user.id)).coins_balance

    await backfill_all_users(session, now=NOW)
    await backfill_all_users(session, now=NOW)  # второй прогон не должен ничего изменить

    balance_after_backfill = (await UserRepository(session).get_by_id(user.id)).coins_balance
    assert balance_after_backfill == balance_after_first_event


async def test_backfill_skips_users_without_workouts(session, user: User):
    checked = await backfill_all_users(session, now=NOW)
    assert checked == 1
    assert await AchievementRepository(session).list_for_user(user.id) == []
