from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkoutSet, WorkoutSetStatus
from app.domain.rules import is_set_complete


class WorkoutSetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_next_set_number(self, user_id: int) -> int:
        result = await self._session.execute(
            select(func.max(WorkoutSet.set_number)).where(WorkoutSet.user_id == user_id),
        )
        current_max = result.scalar_one_or_none()
        return (current_max or 0) + 1

    async def create(self, *, user_id: int, started_from_baseline_id: int) -> WorkoutSet:
        workout_set = WorkoutSet(
            user_id=user_id,
            started_from_baseline_id=started_from_baseline_id,
            set_number=await self.get_next_set_number(user_id),
        )
        self._session.add(workout_set)
        await self._session.flush()
        return workout_set

    async def get_by_id(self, workout_set_id: int) -> WorkoutSet | None:
        return await self._session.get(WorkoutSet, workout_set_id)

    async def get_active_for_user(self, user_id: int) -> WorkoutSet | None:
        result = await self._session.execute(
            select(WorkoutSet)
            .where(WorkoutSet.user_id == user_id, WorkoutSet.status == WorkoutSetStatus.ACTIVE)
            .order_by(WorkoutSet.started_at.desc())
            .limit(1),
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: int) -> list[WorkoutSet]:
        result = await self._session.execute(
            select(WorkoutSet).where(WorkoutSet.user_id == user_id).order_by(WorkoutSet.set_number),
        )
        return list(result.scalars().all())

    async def increment_completed(self, workout_set_id: int, *, completed_at: datetime) -> WorkoutSet:
        """Увеличивает счётчик завершённых тренировок и закрывает сет по
        достижении SET_LENGTH (domain.rules.is_set_complete)."""
        workout_set = await self._session.get_one(WorkoutSet, workout_set_id)
        workout_set.workouts_completed += 1
        if is_set_complete(workout_set.workouts_completed):
            workout_set.status = WorkoutSetStatus.COMPLETED
            workout_set.completed_at = completed_at
        await self._session.flush()
        return workout_set

    async def mark_abandoned(self, workout_set_id: int, *, abandoned_at: datetime) -> WorkoutSet:
        workout_set = await self._session.get_one(WorkoutSet, workout_set_id)
        workout_set.status = WorkoutSetStatus.ABANDONED
        workout_set.completed_at = abandoned_at
        await self._session.flush()
        return workout_set
