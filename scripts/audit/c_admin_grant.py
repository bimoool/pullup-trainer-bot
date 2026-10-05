"""AUDIT C-existing J6: run the sanctioned admin "Выдать подписку" (admin_grant_days) THROUGH the real bot
handler via aiogram Dispatcher.feed_update (same technique as tests/test_bot/conftest.py: StubSession bot,
no network). Usage: c_admin_grant.py <target_telegram_id> <days>. Admin = tg 7300099 (ADMIN_IDS patched in-process only;
the uvicorn server's ADMIN_IDS is untouched). LABEL: bot-handler path (not the bare service call)."""
import asyncio
import sys
from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TgUser

from app.bot.handlers import router
from app.config import settings
from app.db.base import async_session_factory
from app.db.repositories.users import UserRepository
from tests.test_bot.conftest import FAKE_TOKEN, StubSession, make_callback_update

ADMIN_TG = 7300099


def msg(text):
    return Update(update_id=2, message=Message(message_id=101, date=datetime.now(UTC), chat=Chat(id=ADMIN_TG, type="private"),
                  from_user=TgUser(id=ADMIN_TG, is_bot=False, first_name="Admin"), text=text))


async def main(target_tg, days):
    settings.admin_ids = str(ADMIN_TG)
    bot = Bot(token=FAKE_TOKEN, session=StubSession())
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    async with async_session_factory() as s:
        target = await UserRepository(s).get_by_telegram_id(target_tg)
        print("BEFORE", target.subscription_status, target.subscription_expires_at)
        await dp.feed_update(bot, make_callback_update(telegram_id=ADMIN_TG, data=f"admin_grant_days:{target.id}"), session=s)
        await dp.feed_update(bot, msg(str(days)), session=s)
        await s.commit()
        await s.refresh(target)
        print("AFTER", target.subscription_status, target.subscription_expires_at)
        print("BOT SENT:", [getattr(m, "text", None) for m in bot.session.sent_methods])

asyncio.run(main(int(sys.argv[1]), int(sys.argv[2])))
