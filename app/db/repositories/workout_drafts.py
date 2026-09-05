from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkoutDraft


class WorkoutDraftRepository:
    """Один черновик тренировки в реальном времени на пользователя (issue
    #61, см. WorkoutDraft в app/db/models.py) — без сервисного слоя, тот же
    паттерн, что ActiveTimerRepository: чтение/запись одной строки без
    побочных эффектов (монеты/события/ачивки)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_user(self, user_id: int) -> WorkoutDraft | None:
        result = await self._session.execute(
            select(WorkoutDraft).where(WorkoutDraft.user_id == user_id),
        )
        return result.scalar_one_or_none()

    async def save(
        self,
        *,
        user_id: int,
        step_index: int,
        block_a_working_reps: list[int],
        block_a_max_reps: int | None,
        block_b_working_reps: list[int],
        block_b_max_reps: int | None,
        block_a_actual_weight: Decimal | None,
        block_b_actual_weight: Decimal | None,
        block_a_actual_band_item_id: int | None,
        block_b_actual_band_item_id: int | None,
        comment: str | None,
    ) -> WorkoutDraft:
        """Upsert на месте (get-or-create, затем правка полей) — тот же
        приём, что ActiveTimerRepository.start: unique(user_id) и так
        гарантирует не больше одной строки, отдельный delete+insert не
        нужен. Вызывается целиком (все поля разом), не по одному подходу —
        фронтенд уже держит весь накопленный массив в состоянии."""
        draft = await self.get_for_user(user_id)
        if draft is None:
            draft = WorkoutDraft(user_id=user_id)
            self._session.add(draft)
        draft.step_index = step_index
        draft.block_a_working_reps = block_a_working_reps
        draft.block_a_max_reps = block_a_max_reps
        draft.block_b_working_reps = block_b_working_reps
        draft.block_b_max_reps = block_b_max_reps
        draft.block_a_actual_weight = block_a_actual_weight
        draft.block_b_actual_weight = block_b_actual_weight
        draft.block_a_actual_band_item_id = block_a_actual_band_item_id
        draft.block_b_actual_band_item_id = block_b_actual_band_item_id
        draft.comment = comment
        await self._session.flush()
        return draft

    async def delete_for_user(self, user_id: int) -> None:
        """Идемпотентно — если черновика нет, просто ничего не делает."""
        await self._session.execute(delete(WorkoutDraft).where(WorkoutDraft.user_id == user_id))
        await self._session.flush()
