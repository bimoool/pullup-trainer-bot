import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot.handlers import router
from app.bot.middlewares import DbSessionMiddleware
from app.config import settings
from app.workers.tribute_sync import register as register_tribute_sync

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.update.middleware(DbSessionMiddleware())
    dispatcher.include_router(router)
    return dispatcher


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    register_tribute_sync(scheduler)
    return scheduler


async def run_polling() -> None:
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = build_dispatcher()
    scheduler = build_scheduler()

    await bot.delete_webhook(drop_pending_updates=True)
    scheduler.start()
    try:
        await dispatcher.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)


def main() -> None:
    asyncio.run(run_polling())


if __name__ == "__main__":
    main()
