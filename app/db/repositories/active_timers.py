from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActiveTimer, ActiveTimerType


class ActiveTimerRepository:
    """Один активный таймер на пользователя (см. ActiveTimer в app/db/models.py)
    — без сервисного слоя: чтение/запись одной строки без побочных
    эффектов (монеты/события/ачивки), в отличие от WorkoutLogService/
    SubscriptionService (issue #59, план Волны 1)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_user(self, user_id: int) -> ActiveTimer | None:
        result = await self._session.execute(
            select(ActiveTimer).where(ActiveTimer.user_id == user_id),
        )
        return result.scalar_one_or_none()

    async def start(
        self,
        *,
        user_id: int,
        timer_type: ActiveTimerType,
        started_at: datetime,
        duration_seconds: int,
        block_letter: str | None = None,
        set_number: int | None = None,
    ) -> ActiveTimer:
        """Старт нового таймера заменяет предыдущий активный (если был) —
        обновление строки на месте, не delete+insert: unique(user_id)
        и так гарантирует не больше одной строки, отдельная транзакция
        удаления не нужна (тот же приём, что SheetsSyncStateRepository:
        get-or-create, затем правка полей на месте)."""
        timer = await self.get_for_user(user_id)
        if timer is None:
            timer = ActiveTimer(user_id=user_id)
            self._session.add(timer)
        timer.timer_type = timer_type
        timer.started_at = started_at
        timer.duration_seconds = duration_seconds
        timer.block_letter = block_letter
        timer.set_number = set_number
        await self._session.flush()
        return timer

    async def delete_for_user(self, user_id: int) -> None:
        """Идемпотентно — если активного таймера нет, просто ничего не делает."""
        await self._session.execute(delete(ActiveTimer).where(ActiveTimer.user_id == user_id))
        await self._session.flush()
