from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EquipmentItem


class EquipmentItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _next_position(self, user_id: int) -> int:
        result = await self._session.execute(
            select(func.max(EquipmentItem.position)).where(EquipmentItem.user_id == user_id),
        )
        current_max = result.scalar_one_or_none()
        return 0 if current_max is None else current_max + 1

    async def create(self, *, user_id: int, name: str, resistance_kg: Decimal | None = None) -> EquipmentItem:
        item = EquipmentItem(
            user_id=user_id, name=name, resistance_kg=resistance_kg, position=await self._next_position(user_id),
        )
        self._session.add(item)
        await self._session.flush()
        return item

    async def get_by_id(self, equipment_item_id: int) -> EquipmentItem | None:
        return await self._session.get(EquipmentItem, equipment_item_id)

    async def list_for_user(self, user_id: int) -> list[EquipmentItem]:
        """В порядке position — 0 самый тяжёлый (больше всего помощи),
        именно этот порядок определяет "следующий снаряд" при переходах."""
        result = await self._session.execute(
            select(EquipmentItem).where(EquipmentItem.user_id == user_id).order_by(EquipmentItem.position),
        )
        return list(result.scalars().all())

    async def reorder(self, user_id: int, ordered_ids: list[int]) -> list[EquipmentItem]:
        """Переставляет position по новому порядку ordered_ids (весь список
        пользователя, целиком — частичный реордер не запрашивался). Позиции
        переприсваиваются в одной транзакции, полагаясь на
        uq_equipment_items_user_position DEFERRABLE INITIALLY DEFERRED —
        иначе промежуточные UPDATE сталкивались бы друг с другом."""
        items = {item.id: item for item in await self.list_for_user(user_id)}
        for position, item_id in enumerate(ordered_ids):
            items[item_id].position = position
        await self._session.flush()
        return await self.list_for_user(user_id)
