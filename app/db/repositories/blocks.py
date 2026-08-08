from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Block, BlockType

# Запись/изменение blocks намеренно не выведена в отдельный репозиторий:
# блок никогда не создаётся и не редактируется отдельно от своей тренировки
# (target_before/after считаются вместе, каскадом) — вся запись живёт в
# WorkoutRepository, где легче удержать этот инвариант в одном месте. Здесь —
# только чтение, для случаев, когда нужны блоки без всей тренировки целиком.


class BlockRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_workout(self, workout_id: int) -> list[Block]:
        result = await self._session.execute(
            select(Block).where(Block.workout_id == workout_id).order_by(Block.block_type),
        )
        return list(result.scalars().all())

    async def get_by_workout_and_type(self, workout_id: int, block_type: BlockType) -> Block | None:
        result = await self._session.execute(
            select(Block).where(Block.workout_id == workout_id, Block.block_type == block_type),
        )
        return result.scalar_one_or_none()
