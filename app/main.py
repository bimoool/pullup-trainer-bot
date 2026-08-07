import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.bot.handlers import router
from app.config import settings

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


async def run_polling() -> None:
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = build_dispatcher()

    await bot.delete_webhook(drop_pending_updates=True)
    await dispatcher.start_polling(bot)


def main() -> None:
    asyncio.run(run_polling())


if __name__ == "__main__":
    main()
