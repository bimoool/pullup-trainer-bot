import logging
from datetime import UTC, datetime

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.bot import texts
from app.bot.states import AdminStates
from app.config import settings

logger = logging.getLogger(__name__)

JOB_ID = "weekly_digest_reminder"


async def send_weekly_digest_reminder(bot: Bot, dispatcher: Dispatcher) -> None:
    """Не рассылка сама по себе — только напоминание админу(ам) её
    написать. Ответ приходит обычным сообщением в чат с ботом и ловится
    handle_weekly_digest_reply (app/bot/handlers/admin.py) через FSM-
    состояние AdminStates.waiting_for_weekly_digest_text, выставленное
    здесь программно (не через колбэк — тут нет входящего Update, только
    сработавший таймер): это и есть привязка ответа именно к ЭТОМУ
    напоминанию, не к случайному сообщению боту. weekly_digest_reminder_
    sent_at в данных состояния — момент отправки, от него хендлер
    отсчитывает WEEKLY_DIGEST_REPLY_DEADLINE_HOURS при получении ответа.

    dispatcher.fsm.get_context(bot=..., chat_id=..., user_id=...) — тот
    же способ получить FSMContext вне живого Update, что использует
    tests/test_bot/conftest.py для прямой проверки состояния в тестах;
    здесь тот же приём применяется по-настоящему, не только в тестах."""
    now = datetime.now(UTC)
    for admin_id in settings.admin_id_list:
        try:
            await bot.send_message(admin_id, texts.ADMIN_WEEKLY_DIGEST_REMINDER)
        except TelegramAPIError:
            logger.warning("weekly_digest: failed to send reminder to admin %s", admin_id, exc_info=True)
            continue

        fsm = dispatcher.fsm.get_context(bot=bot, chat_id=admin_id, user_id=admin_id)
        await fsm.set_state(AdminStates.waiting_for_weekly_digest_text)
        await fsm.update_data(weekly_digest_reminder_sent_at=now.isoformat())
        logger.info("weekly_digest: reminder sent to admin %s", admin_id)


def register(scheduler: AsyncIOScheduler, bot: Bot, dispatcher: Dispatcher) -> None:
    # Воскресенье, 18:00 UTC (~21:00 по Москве) — "вечер воскресенья" перед
    # началом рабочей недели пользователей.
    scheduler.add_job(
        send_weekly_digest_reminder, CronTrigger(day_of_week="sun", hour=18),
        id=JOB_ID, kwargs={"bot": bot, "dispatcher": dispatcher},
    )
