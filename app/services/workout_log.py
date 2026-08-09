from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BlockType, EquipmentType, Workout, WorkoutSetStatus
from app.db.repositories.events import EventRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.achievements import (
    AchievementCode,
    check_equipment_changed,
    check_first_weighted_pullup,
    check_set_completed,
)
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

    Разблокированы тут только EQUIPMENT_CHANGED и SET_COMPLETED — они
    напрямую следуют из результата этого вызова, плюс
    FIRST_WEIGHTED_PULLUP (первая тренировка силового блока на
    отягощении). TEN_WORKOUTS_STREAK, MAX_REPS_PLUS_FIVE и MONTH_NO_GAPS
    сознательно не реализованы: требуют аккуратного чтения истории — не
    гадаю с реализацией, оставляю на отдельный проход."""

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
        block_a_equipment_type: EquipmentType,
        block_a_equipment_value: Decimal | None,
        block_b_equipment_type: EquipmentType,
        block_b_equipment_value: Decimal | None,
        comment: str | None = None,
    ) -> Workout:
        workout = await self._workouts.record_workout(
            user_id=user_id,
            workout_set_id=workout_set_id,
            performed_at=performed_at,
            block_a_reps=block_a_reps,
            block_b_reps=block_b_reps,
            block_a_equipment_type=block_a_equipment_type,
            block_a_equipment_value=block_a_equipment_value,
            block_b_equipment_type=block_b_equipment_type,
            block_b_equipment_value=block_b_equipment_value,
            comment=comment,
        )

        await self._events.create(
            user_id=user_id, event_type="workout_completed", payload={"workout_id": workout.id},
        )
        await self._gamification.award_workout_coins(user_id, COINS_PER_WORKOUT)
        await self._unlock_workout_achievements(user_id, workout)
        return workout

    async def record_backdated_workout(
        self,
        *,
        user_id: int,
        workout_set_id: int,
        performed_at: datetime,
        block_a_reps: BlockLog,
        block_b_reps: BlockLog,
        block_a_equipment_type: EquipmentType,
        block_a_equipment_value: Decimal | None,
        block_b_equipment_type: EquipmentType,
        block_b_equipment_value: Decimal | None,
        comment: str | None = None,
    ) -> Workout:
        """Не участвует в каскаде (см. WorkoutRepository.record_backdated_workout),
        поэтому и ачивки на переход снаряда/закрытие сета здесь не
        проверяем — closing a set задним числом можно, но статус сета
        WorkoutSetRepository.increment_completed уже обновит сам."""
        workout = await self._workouts.record_backdated_workout(
            user_id=user_id,
            workout_set_id=workout_set_id,
            performed_at=performed_at,
            block_a_reps=block_a_reps,
            block_b_reps=block_b_reps,
            block_a_equipment_type=block_a_equipment_type,
            block_a_equipment_value=block_a_equipment_value,
            block_b_equipment_type=block_b_equipment_type,
            block_b_equipment_value=block_b_equipment_value,
            comment=comment,
        )
        await self._events.create(
            user_id=user_id, event_type="workout_backdated", payload={"workout_id": workout.id},
        )
        return workout

    async def _unlock_workout_achievements(self, user_id: int, workout: Workout) -> None:
        block_a = next(b for b in workout.blocks if b.block_type == BlockType.A)
        block_b = next(b for b in workout.blocks if b.block_type == BlockType.B)

        if block_b.equipment_type == EquipmentType.WEIGHT:
            history = await self._workouts.list_for_user(user_id)
            weighted_workouts = [
                w for w in history
                if any(b.block_type == BlockType.B and b.equipment_type == EquipmentType.WEIGHT for b in w.blocks)
            ]
            is_first_weighted = len(weighted_workouts) == 1  # только та, что мы сейчас записали
            if check_first_weighted_pullup(is_first_weighted):
                await self._gamification.unlock_achievement(
                    user_id=user_id, code=AchievementCode.FIRST_WEIGHTED_PULLUP, coins_reward=ACHIEVEMENT_COINS,
                )

        if check_equipment_changed(block_a.equipment_changed or block_b.equipment_changed):
            await self._gamification.unlock_achievement(
                user_id=user_id, code=AchievementCode.EQUIPMENT_CHANGED, coins_reward=ACHIEVEMENT_COINS,
            )

        workout_set = await self._workout_sets.get_by_id(workout.workout_set_id)
        just_completed = workout_set.status == WorkoutSetStatus.COMPLETED
        if check_set_completed(just_completed):
            await self._gamification.unlock_achievement(
                user_id=user_id, code=AchievementCode.SET_COMPLETED, coins_reward=ACHIEVEMENT_COINS,
            )
