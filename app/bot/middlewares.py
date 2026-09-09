import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from app.db.base import async_session_factory

# Telegram шлёт альбом (несколько фото к одной рассылке) не одним Update, а
# несколькими отдельными Update с общим media_group_id — сколько частей,
# столько и Update. Части одного альбома обычно приходят с разницей в
# десятки-сотни мс, не секунды — ALBUM_DEBOUNCE_SECONDS с большим запасом.
ALBUM_DEBOUNCE_SECONDS = 0.7


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


class MediaGroupMiddleware(BaseMiddleware):
    """Буферизация Update по media_group_id перед обработкой (issue #72).

    aiogram-диспетчер в реальном polling обрабатывает Update конкурентными
    asyncio-задачами (`Dispatcher._polling`, `handle_as_tasks=True` по
    умолчанию), не дожидаясь завершения хендлера предыдущего. Альбом из
    нескольких фото — это несколько таких Update с общим media_group_id, у
    каждого своё отдельное Message с одним фото; без буферизации каждое из
    них по отдельности ловило FSM-состояние (например, waiting_for_broadcast_
    text) и самостоятельно запускало хендлер — «одно фото с подписью,
    остальные отдельными сообщениями без текста».

    Только первая часть альбома ждёт ALBUM_DEBOUNCE_SECONDS, копит остальные
    части в общем буфере (id альбома -> список Message) и передаёт их все
    хендлеру одним вызовом через data["album"]; последующие части того же
    альбома только добавляют себя в буфер и завершаются без вызова
    хендлера — иначе хендлер запускался бы ещё раз на каждую из них.
    Сообщения без media_group_id (обычный текст/одиночное фото) проходят
    без изменений — data["album"] для них не выставляется."""

    def __init__(self) -> None:
        self._albums: dict[str, list[Message]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.media_group_id is None:
            return await handler(event, data)

        media_group_id = event.media_group_id
        album = self._albums.setdefault(media_group_id, [])
        album.append(event)
        if len(album) > 1:
            # Не первая часть альбома — уже добавила себя в общий буфер выше,
            # первая часть заберёт её после debounce ниже.
            return None

        await asyncio.sleep(ALBUM_DEBOUNCE_SECONDS)
        del self._albums[media_group_id]
        data["album"] = album
        return await handler(event, data)
