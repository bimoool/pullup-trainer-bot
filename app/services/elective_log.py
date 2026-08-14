from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ElectiveWorkout, EquipmentType
from app.db.repositories.elective_workouts import ElectiveWorkoutRepository
from app.db.repositories.events import EventRepository
from app.domain.electives import ElectiveType


class ElectiveLogService:
    """Оркестрация записи факультатива: сама запись (ElectiveWorkoutRepository)
    + событие в аналитику (EventRepository, тот же канал, что фидбек и
    /workers/sheets_sync.py). Без монет/ачивок — тот же прецедент, что и
    для свободных подтягиваний/бэкдейта: вне плана, не про мотивацию
    выполнения цикла из 12, а про опциональную дополнительную нагрузку."""

    def __init__(self, session: AsyncSession) -> None:
        self._electives = ElectiveWorkoutRepository(session)
        self._events = EventRepository(session)

    async def record(
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
        elective = await self._electives.create(
            user_id=user_id, elective_type=elective_type, performed_at=performed_at,
            total_reps=total_reps, reps_sequence=reps_sequence,
            equipment_type=equipment_type, equipment_value=equipment_value,
            equipment_item_id=equipment_item_id,
        )
        await self._events.create(
            user_id=user_id, event_type="elective_completed",
            payload={"elective_type": elective_type.value, "volume": total_reps},
        )
        return elective
