from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ElectiveWorkout, EquipmentType
from app.db.repositories.elective_workouts import ElectiveWorkoutRepository
from app.db.repositories.events import EventRepository
from app.domain.electives import ELECTIVE_WEEK_WINDOW_DAYS, ElectiveType, is_elective_allowed
from app.services.achievement_checks import unlock_volume_milestones


async def is_elective_available(session: AsyncSession, user_id: int, *, now: datetime) -> bool:
    """Общая проверка недельного лимита (issue #94) — используется и
    реактивно (handle_start_workout/handle_electives_start), и проактивно
    (handle_workout_section), чтобы запрос "сколько факультативов за
    последнюю неделю" не дублировался в каждом хендлере отдельно."""
    week_ago = now - timedelta(days=ELECTIVE_WEEK_WINDOW_DAYS)
    count_this_week = await ElectiveWorkoutRepository(session).count_since(user_id, week_ago)
    return is_elective_allowed(count_this_week)


class ElectiveLogService:
    """Оркестрация записи факультатива: сама запись (ElectiveWorkoutRepository)
    + событие в аналитику (EventRepository, тот же канал, что фидбек и
    /workers/sheets_sync.py). Монет за сам факультатив нет — тот же
    прецедент, что и для свободных подтягиваний/бэкдейта: вне плана, не
    про мотивацию выполнения цикла из 12. Но факультативы входят в
    пожизненный объём подтягиваний (ревизия ачивок) — проверяем пороги
    VOLUME_* после каждой записи."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
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
        await unlock_volume_milestones(self._session, user_id)
        return elective
