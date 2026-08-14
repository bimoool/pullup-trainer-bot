from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Event


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, user_id: int, event_type: str, payload: dict | None = None) -> Event:
        event = Event(user_id=user_id, event_type=event_type, payload=payload or {})
        self._session.add(event)
        await self._session.flush()
        return event

    async def list_for_user(self, user_id: int, *, limit: int = 100) -> list[Event]:
        result = await self._session.execute(
            select(Event).where(Event.user_id == user_id).order_by(Event.created_at.desc()).limit(limit),
        )
        return list(result.scalars().all())

    async def list_since(self, after_id: int, *, limit: int) -> list[Event]:
        """Все события с id > after_id, по возрастанию id, ограничено limit
        (app/workers/sheets_sync.py — выгружает страницами, чтобы один
        цикл синка не пытался утащить неограниченный бэклог одним батчем)."""
        result = await self._session.execute(
            select(Event).where(Event.id > after_id).order_by(Event.id).limit(limit),
        )
        return list(result.scalars().all())
