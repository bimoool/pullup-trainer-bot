from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.db.base import async_session_factory


class DbSessionMiddleware(BaseMiddleware):
    """Одна сессия на апдейт, коммит после хендлера. Если хендлер бросает
    исключение — коммит не достигается, `async with` откатывает и закрывает
    сессию сам (стандартное поведение AsyncSession.__aexit__)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with async_session_factory() as session:
            data["session"] = session
            result = await handler(event, data)
            await session.commit()
            return result
