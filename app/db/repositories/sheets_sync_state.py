from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SheetsSyncState

_SINGLETON_ID = 1


class SheetsSyncStateRepository:
    """Курсоры выгрузки в Google Sheets — одна строка (см. SheetsSyncState),
    по одному last_*_id на каждый инкрементальный источник. _get_state
    создаёт строку при первом обращении, если её ещё нет (первый запуск
    воркера на чистой БД)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_state(self) -> SheetsSyncState:
        state = await self._session.get(SheetsSyncState, _SINGLETON_ID)
        if state is None:
            state = SheetsSyncState(id=_SINGLETON_ID)
            self._session.add(state)
            await self._session.flush()
        return state

    async def get_last_event_id(self) -> int:
        return (await self._get_state()).last_event_id

    async def set_last_event_id(self, event_id: int) -> None:
        state = await self._get_state()
        state.last_event_id = event_id
        await self._session.flush()

    async def get_last_workout_id(self) -> int:
        return (await self._get_state()).last_workout_id

    async def set_last_workout_id(self, workout_id: int) -> None:
        state = await self._get_state()
        state.last_workout_id = workout_id
        await self._session.flush()

    async def get_last_elective_id(self) -> int:
        return (await self._get_state()).last_elective_id

    async def set_last_elective_id(self, elective_id: int) -> None:
        state = await self._get_state()
        state.last_elective_id = elective_id
        await self._session.flush()

    async def get_last_subscription_id(self) -> int:
        return (await self._get_state()).last_subscription_id

    async def set_last_subscription_id(self, subscription_id: int) -> None:
        state = await self._get_state()
        state.last_subscription_id = subscription_id
        await self._session.flush()

    async def get_last_coin_id(self) -> int:
        return (await self._get_state()).last_coin_id

    async def set_last_coin_id(self, coin_id: int) -> None:
        state = await self._get_state()
        state.last_coin_id = coin_id
        await self._session.flush()

    async def get_last_achievement_id(self) -> int:
        return (await self._get_state()).last_achievement_id

    async def set_last_achievement_id(self, achievement_id: int) -> None:
        state = await self._get_state()
        state.last_achievement_id = achievement_id
        await self._session.flush()

    async def get_last_baseline_id(self) -> int:
        return (await self._get_state()).last_baseline_id

    async def set_last_baseline_id(self, baseline_id: int) -> None:
        state = await self._get_state()
        state.last_baseline_id = baseline_id
        await self._session.flush()
