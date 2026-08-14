from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SheetsSyncState

_SINGLETON_ID = 1


class SheetsSyncStateRepository:
    """Курсор выгрузки в Google Sheets — одна строка (см. SheetsSyncState).
    get_last_event_id создаёт строку при первом обращении, если её ещё
    нет (первый запуск воркера на чистой БД)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_last_event_id(self) -> int:
        state = await self._session.get(SheetsSyncState, _SINGLETON_ID)
        if state is None:
            state = SheetsSyncState(id=_SINGLETON_ID, last_event_id=0)
            self._session.add(state)
            await self._session.flush()
        return state.last_event_id

    async def set_last_event_id(self, event_id: int) -> None:
        state = await self._session.get(SheetsSyncState, _SINGLETON_ID)
        if state is None:
            state = SheetsSyncState(id=_SINGLETON_ID, last_event_id=event_id)
            self._session.add(state)
        else:
            state.last_event_id = event_id
        await self._session.flush()
