from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ElectiveWorkout
from app.domain.constants import EquipmentType
from app.domain.electives import ElectiveType


class ElectiveWorkoutRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: int,
        elective_type: ElectiveType,
        performed_at: datetime,
        total_reps: int,
        reps_sequence: list[int] | None,
        equipment_type: EquipmentType,
        equipment_value: Decimal | None = None,
        equipment_item_id: int | None = None,
    ) -> ElectiveWorkout:
        elective = ElectiveWorkout(
            user_id=user_id,
            elective_type=elective_type,
            performed_at=performed_at,
            total_reps=total_reps,
            reps_sequence=reps_sequence,
            equipment_type=equipment_type,
            equipment_value=equipment_value,
            equipment_item_id=equipment_item_id,
        )
        self._session.add(elective)
        await self._session.flush()
        return elective

    async def list_types_for_user(self, user_id: int) -> list[ElectiveType]:
        """Хронологический порядок (старые первыми) — вход для
        app.domain.electives.available_elective_types."""
        result = await self._session.execute(
            select(ElectiveWorkout.elective_type)
            .where(ElectiveWorkout.user_id == user_id)
            .order_by(ElectiveWorkout.performed_at),
        )
        return list(result.scalars().all())

    async def total_reps_for_user(self, user_id: int) -> int:
        """Пожизненная сумма total_reps — вход для ачивок за объём
        (app.services.achievement_checks.unlock_volume_milestones).
        SQL SUM, а не list_for_user (тот ограничен limit=100 — годится для
        отображения истории, но не для пожизненного тотала)."""
        result = await self._session.execute(
            select(func.coalesce(func.sum(ElectiveWorkout.total_reps), 0))
            .where(ElectiveWorkout.user_id == user_id),
        )
        return result.scalar_one()

    async def count_since(self, user_id: int, since: datetime) -> int:
        """Вход для app.domain.electives.is_elective_allowed — сколько
        факультативов сделано за скользящее окно (см. ELECTIVE_WEEK_WINDOW_DAYS)."""
        result = await self._session.execute(
            select(func.count())
            .select_from(ElectiveWorkout)
            .where(ElectiveWorkout.user_id == user_id, ElectiveWorkout.performed_at >= since),
        )
        return result.scalar_one()

    async def list_for_user(self, user_id: int, *, limit: int = 100) -> list[ElectiveWorkout]:
        result = await self._session.execute(
            select(ElectiveWorkout)
            .where(ElectiveWorkout.user_id == user_id)
            .order_by(ElectiveWorkout.performed_at.desc())
            .limit(limit),
        )
        return list(result.scalars().all())

    async def list_since(self, after_id: int, *, limit: int) -> list[ElectiveWorkout]:
        """Факультативы ЛЮБОГО пользователя с id > after_id, по возрастанию
        id — вход для app.workers.sheets_sync.py (пишет в тот же лист
        "workouts", что и WorkoutRepository.list_since, но со своим
        курсором)."""
        result = await self._session.execute(
            select(ElectiveWorkout).where(ElectiveWorkout.id > after_id).order_by(ElectiveWorkout.id).limit(limit),
        )
        return list(result.scalars().all())
