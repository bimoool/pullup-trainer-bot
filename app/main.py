import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot.error_handler import register_error_handler
from app.bot.handlers import router
from app.bot.middlewares import DbSessionMiddleware
from app.config import settings
from app.workers.robokassa_sync import register as register_robokassa_sync
from app.workers.sheets_sync import register as register_sheets_sync
from app.workers.tribute_sync import register as register_tribute_sync
from app.workers.weekly_report import register as register_weekly_report

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

# /admin намеренно не входит — доступен по прямому вводу для белого списка
# администраторов (см. Часть 7), но не должен предлагаться всем в автодополнении.
BOT_COMMANDS = [
    BotCommand(command="start", description="Начать / вернуться в начало"),
    BotCommand(command="cancel", description="Отменить текущий шаг"),
    BotCommand(command="help", description="Помощь"),
]


def build_dispatcher() -> Dispatcher:
    # Redis, не MemoryStorage: состояние диалога обязано пережить рестарт
    # процесса — иначе пользователь, застрявший посреди тренировки/анкеты
    # во время деплоя, теряет прогресс и упирается в тупик.
    storage = RedisStorage.from_url(settings.redis_url)
    dispatcher = Dispatcher(storage=storage)
    dispatcher.update.middleware(DbSessionMiddleware())
    register_error_handler(dispatcher)
    dispatcher.include_router(router)
    return dispatcher


def build_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    register_tribute_sync(scheduler, bot)
    register_robokassa_sync(scheduler, bot)
    register_weekly_report(scheduler, bot)
    register_sheets_sync(scheduler)
    return scheduler


async def run_polling() -> None:
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = build_dispatcher()
    scheduler = build_scheduler(bot)

    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_my_commands(BOT_COMMANDS)
    scheduler.start()
    try:
        await dispatcher.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)


def main() -> None:
    asyncio.run(run_polling())


if __name__ == "__main__":
    main()
