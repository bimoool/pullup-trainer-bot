"""E2E-помощник WEB-AUTH: проводит подтверждение входа через НАСТОЯЩИЙ aiogram-роутинг (Dispatcher.feed_update,
исходящие вызовы Telegram перехватывает заглушка) — тем же путём, что реальный бот: /start weblogin_<id>, затем
нажатие «Подтвердить» (callback.from_user = нажавший, message.from_user = бот, как в реальном Telegram).

usage: python scripts/e2e_web_login.py <request_id> <telegram_id> [confirm|deny|open]   (по умолчанию confirm)
       python scripts/e2e_web_login.py - <telegram_id> count   -> {"users": N}  (строк users с этим telegram_id)
Печатает JSON {"messages": [...текст ответов бота...]}.
"""

import asyncio
import json
import sys
from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, MessageEntity, Update
from aiogram.types import User as TgUser

from app.bot.handlers import router
from app.bot.middlewares import DbSessionMiddleware

FAKE_TOKEN = "123456789:AAFakeTokenForE2EOnly0000000000000000000"
BOT_ID = 123456789


class _Stub(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list = []

    async def close(self) -> None:
        return None

    async def make_request(self, bot, method, timeout=None):
        self.sent.append(method)
        if isinstance(method.__returning__, bool | type(None)):
            return True
        return Message(message_id=1, date=datetime.now(UTC), chat=Chat(id=1, type="private"), text="stub")

    async def stream_content(self, *args, **kwargs):
        yield b""


def _start(telegram_id: int, payload: str) -> Update:
    return Update(update_id=1, message=Message(
        message_id=7, date=datetime.now(UTC), chat=Chat(id=telegram_id, type="private"),
        from_user=TgUser(id=telegram_id, is_bot=False, first_name="E2E", username="e2e"),
        text=f"/start {payload}", entities=[MessageEntity(type="bot_command", offset=0, length=6)],
    ))


def _callback(telegram_id: int, data: str) -> Update:
    message = Message(
        message_id=8, date=datetime.now(UTC), chat=Chat(id=telegram_id, type="private"),
        from_user=TgUser(id=BOT_ID, is_bot=True, first_name="Bot"), text="stub",
    )
    return Update(update_id=2, callback_query=CallbackQuery(
        id="1", from_user=TgUser(id=telegram_id, is_bot=False, first_name="E2E", username="e2e"),
        chat_instance="1", data=data, message=message,
    ))


async def count_users(telegram_id: int) -> None:
    from sqlalchemy import func, select

    from app.db.base import async_session_factory
    from app.db.models import User

    async with async_session_factory() as db:
        n = (await db.execute(select(func.count()).select_from(User).where(User.telegram_id == telegram_id))).scalar_one()
    print(json.dumps({"users": n}))


async def main(request_id: str, telegram_id: int, action: str) -> None:
    if action == "count":
        await count_users(telegram_id)
        return
    session = _Stub()
    bot = Bot(token=FAKE_TOKEN, session=session)
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.update.middleware(DbSessionMiddleware())
    dispatcher.include_router(router)
    await dispatcher.feed_update(bot, _start(telegram_id, f"weblogin_{request_id}"))
    if action == "confirm":
        await dispatcher.feed_update(bot, _callback(telegram_id, f"wl:ok:{request_id}"))
    elif action == "deny":
        await dispatcher.feed_update(bot, _callback(telegram_id, f"wl:no:{request_id}"))
    messages = [m.text for m in session.sent if isinstance(m, SendMessage | EditMessageText)]
    print(json.dumps({"messages": messages}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], int(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "confirm"))
