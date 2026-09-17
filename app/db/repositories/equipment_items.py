from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EquipmentItem, WorkoutDraft


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

    async def rename(self, *, item_id: int, user_id: int, name: str) -> EquipmentItem | None:
        """Переименование (issue #148) — правит только name, resistance_kg/
        position не трогает (для этого есть create/reorder). Возвращает
        None, если резина не найдена или принадлежит другому пользователю —
        вызывающий код (app/web/routes.py) превращает это в 404, не 403,
        тем же принципом, что остальные ownership-проверки этого файла (не
        подтверждать чужому пользователю сам факт существования id)."""
        item = await self.get_by_id(item_id)
        if item is None or item.user_id != user_id:
            return None
        item.name = name
        await self._session.flush()
        return item

    async def delete(self, *, item_id: int, user_id: int) -> bool:
        """Настоящий DELETE, не архивация — это личный справочник
        пользователя, не история тренировок (см. докстринг EquipmentItem).
        blocks.equipment_item_id/elective_workouts.equipment_item_id —
        ON DELETE SET NULL (миграция e7c2a4f9d1b3), поэтому уже записанные
        тренировки/факультативы не мешают удалению и не ломаются: имя на
        момент тренировки уже отдельно сохранено в equipment_item_name.

        WorkoutDraft.block_*_actual_band_item_id — не FK (черновик не
        хранит snapshot плана вообще, см. докстринг WorkoutDraft), поэтому
        Postgres не подчистит их сам — обнуляем вручную, чтобы черновик не
        указывал на несуществующий id (сам черновик эфемерен, это не потеря
        данных)."""
        item = await self.get_by_id(item_id)
        if item is None or item.user_id != user_id:
            return False
        await self._session.execute(
            update(WorkoutDraft)
            .where(
                WorkoutDraft.user_id == user_id,
                WorkoutDraft.block_a_actual_band_item_id == item_id,
            )
            .values(block_a_actual_band_item_id=None),
        )
        await self._session.execute(
            update(WorkoutDraft)
            .where(
                WorkoutDraft.user_id == user_id,
                WorkoutDraft.block_b_actual_band_item_id == item_id,
            )
            .values(block_b_actual_band_item_id=None),
        )
        await self._session.delete(item)
        await self._session.flush()
        return True

    async def list_for_user(self, user_id: int) -> list[EquipmentItem]:
        """В порядке position — 0 самый тяжёлый (больше всего помощи),
        именно этот порядок определяет "следующий снаряд" при переходах."""
        result = await self._session.execute(
            select(EquipmentItem).where(EquipmentItem.user_id == user_id).order_by(EquipmentItem.position),
        )
        return list(result.scalars().all())

    async def list_all(self) -> list[EquipmentItem]:
        """Личный список резин ВСЕХ пользователей — вход для
        app.workers.sheets_sync.py (лист "equipment_items", снапшот, как
        users — список редко меняется и мал, инкремент избыточен)."""
        result = await self._session.execute(
            select(EquipmentItem).order_by(EquipmentItem.user_id, EquipmentItem.position),
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
