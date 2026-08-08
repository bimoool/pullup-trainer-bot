from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BlockType, Workout, WorkoutSetStatus
from app.db.repositories.events import EventRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.achievements import AchievementCode, check_band_changed, check_set_completed
from app.domain.session import BlockLog
from app.services.gamification import GamificationService

# Суммы монет не определены (см. app/services/onboarding.py) — начисляем 0,
# но фиксируем сам факт (тренировка/ачивка), чтобы история и уведомления
# работали уже сейчас.
COINS_PER_WORKOUT = 0
ACHIEVEMENT_COINS = 0


class WorkoutLogService:
    """Оркестрирует запись тренировки: сама тренировка (WorkoutRepository,
    с его каскадом и sequence_number) + событие в аналитику + монеты за
    тренировку + проверка ачивок, которые можно определить прямо здесь.

    Разблокированы тут только BAND_CHANGED и SET_COMPLETED — они напрямую
    следуют из результата этого вызова. TEN_WORKOUTS_STREAK, MAX_REPS_PLUS_FIVE
    и MONTH_NO_GAPS сознательно не реализованы: они требуют аккуратного
    чтения истории (стрик с учётом откатов, объём на момент замера, разрывы
    за 30 дней) — не гадаю с реализацией, оставляю на отдельный проход."""

    def __init__(self, session: AsyncSession) -> None:
        self._workouts = WorkoutRepository(session)
        self._workout_sets = WorkoutSetRepository(session)
        self._events = EventRepository(session)
        self._gamification = GamificationService(session)

    async def record_workout(
        self,
        *,
        user_id: int,
        workout_set_id: int,
        performed_at: datetime,
        block_a_reps: BlockLog,
        block_b_reps: BlockLog,
        band_thickness_mm: Decimal,
        weight_kg: Decimal,
        comment: str | None = None,
    ) -> Workout:
        is_first_workout = await self._workouts.list_for_user(user_id) == []

        workout = await self._workouts.record_workout(
            user_id=user_id,
            workout_set_id=workout_set_id,
            performed_at=performed_at,
            block_a_reps=block_a_reps,
            block_b_reps=block_b_reps,
            band_thickness_mm=band_thickness_mm,
            weight_kg=weight_kg,
            comment=comment,
        )

        await self._events.create(
            user_id=user_id, event_type="workout_completed", payload={"workout_id": workout.id},
        )
        await self._gamification.award_workout_coins(user_id, COINS_PER_WORKOUT)
        await self._unlock_workout_achievements(user_id, workout, is_first_workout=is_first_workout)
        return workout

    async def _unlock_workout_achievements(
        self, user_id: int, workout: Workout, *, is_first_workout: bool,
    ) -> None:
        if is_first_workout:
            await self._gamification.unlock_achievement(
                user_id=user_id, code=AchievementCode.FIRST_WEIGHTED_PULLUP, coins_reward=ACHIEVEMENT_COINS,
            )

        block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
        if check_band_changed(block_a.equipment_changed):
            await self._gamification.unlock_achievement(
                user_id=user_id, code=AchievementCode.BAND_CHANGED, coins_reward=ACHIEVEMENT_COINS,
            )

        workout_set = await self._workout_sets.get_by_id(workout.workout_set_id)
        just_completed = workout_set.status == WorkoutSetStatus.COMPLETED
        if check_set_completed(just_completed):
            await self._gamification.unlock_achievement(
                user_id=user_id, code=AchievementCode.SET_COMPLETED, coins_reward=ACHIEVEMENT_COINS,
            )
