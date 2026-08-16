from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.elective_workouts import ElectiveWorkoutRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.achievements import (
    AchievementCode,
    check_max_reps_gain,
    check_month_without_gaps,
    check_volume_milestones,
    check_workout_streak,
    consecutive_streak_length,
)
from app.services.gamification import GamificationService

TEN_WORKOUTS_STREAK_COINS = 100
MAX_REPS_PLUS_TEN_COINS = 100
MONTH_NO_GAPS_COINS = 150

VOLUME_MILESTONE_COINS: dict[AchievementCode, int] = {
    AchievementCode.VOLUME_100: 20,
    AchievementCode.VOLUME_1000: 100,
    AchievementCode.VOLUME_10000: 300,
    AchievementCode.VOLUME_100000: 1000,
}


async def unlock_history_achievements(session: AsyncSession, user_id: int, *, now: datetime) -> None:
    """TEN_WORKOUTS_STREAK, MONTH_NO_GAPS, MAX_REPS_PLUS_TEN — все три
    считаются из ПОЛНОЙ истории пользователя (не только события, которое
    вызвало проверку), поэтому безопасно вызывать после записи любой
    тренировки (обычной/бэкдейта/свободной) и из разового бэкфилл-скрипта
    (scripts/backfill_achievements.py) — unlock_achievement идемпотентен,
    повторные срабатывания не начисляют монеты дважды.

    now — явный параметр (тот же принцип, что и в SubscriptionService.extend/
    RobokassaService.sync_pending_payments), а не datetime.now() внутри:
    MONTH_NO_GAPS должен считаться от РЕАЛЬНОГО текущего момента, а не от
    performed_at записи (иначе бэкдейт задним числом искажал бы окно) — и
    это же делает функцию тестируемой без монки reального времени."""
    workouts = WorkoutRepository(session)
    records = await workouts.list_records_for_user(user_id)
    if not records:
        return

    gamification = GamificationService(session)
    dates = [r.performed_at.date() for r in records]

    streak = consecutive_streak_length(dates)
    if check_workout_streak(streak):
        await gamification.unlock_achievement(
            user_id=user_id, code=AchievementCode.TEN_WORKOUTS_STREAK, coins_reward=TEN_WORKOUTS_STREAK_COINS,
        )

    if check_month_without_gaps(dates, now.date()):
        await gamification.unlock_achievement(
            user_id=user_id, code=AchievementCode.MONTH_NO_GAPS, coins_reward=MONTH_NO_GAPS_COINS,
        )

    baseline = await BaselineRepository(session).get_latest_for_user(user_id)
    if baseline is not None:
        # Лучший результат по любому из блоков за всю историю — не только
        # блок A (объёмный), т.к. оба блока могут покидать собственный вес
        # (см. suggest_starting_equipment) и напрямую сопоставлять замер
        # только с одним из них было бы произвольным выбором.
        max_reps_now = max(max(r.block_a.log.max_reps, r.block_b.log.max_reps) for r in records)
        if check_max_reps_gain(max_reps_now, baseline.reps):
            await gamification.unlock_achievement(
                user_id=user_id, code=AchievementCode.MAX_REPS_PLUS_TEN, coins_reward=MAX_REPS_PLUS_TEN_COINS,
            )


async def unlock_volume_milestones(session: AsyncSession, user_id: int) -> None:
    """Пожизненный объём подтягиваний — обычные тренировки (в т.ч. бэкдейт
    и свободные) плюс факультативы. Не переиспользует
    app.domain.reports.all_cycles_analytics: тот считает только Workout,
    без ElectiveWorkout — здесь собственная сумма из обоих источников."""
    workouts = WorkoutRepository(session)
    electives = ElectiveWorkoutRepository(session)
    gamification = GamificationService(session)

    records = await workouts.list_records_for_user(user_id)
    workout_volume = sum(r.block_a.log.volume + r.block_b.log.volume for r in records)
    elective_volume = await electives.total_reps_for_user(user_id)
    total_volume = workout_volume + elective_volume

    for code in check_volume_milestones(total_volume):
        await gamification.unlock_achievement(user_id=user_id, code=code, coins_reward=VOLUME_MILESTONE_COINS[code])
