"""MediaGroupMiddleware — порядок частей альбома (pre-G3 stabilization).

Update альбома приходят конкурентными asyncio-задачами, порядок их входа в
middleware недетерминирован; хендлер должен получать части по message_id."""

import asyncio
from datetime import UTC, datetime

from aiogram.types import Chat, Message, PhotoSize

from app.bot.middlewares import MediaGroupMiddleware


def _part(message_id: int) -> Message:
    return Message(
        message_id=message_id, date=datetime.now(UTC), chat=Chat(id=1, type="private"),
        media_group_id="album-order",
        photo=[PhotoSize(file_id=f"f{message_id}", file_unique_id=f"u{message_id}", width=1, height=1)],
    )


async def test_album_parts_are_delivered_sorted_by_message_id(monkeypatch):
    monkeypatch.setattr("app.bot.middlewares.ALBUM_DEBOUNCE_SECONDS", 0.05)
    received: list[list[int]] = []

    async def handler(event, data):
        received.append([m.message_id for m in data["album"]])

    middleware = MediaGroupMiddleware()
    # Приход в обратном порядке: первым (владельцем буфера) — не самый
    # меньший message_id.
    arrival = [_part(303), _part(301), _part(302)]
    await asyncio.gather(*(middleware(handler, m, {}) for m in arrival))

    assert received == [[301, 302, 303]]
