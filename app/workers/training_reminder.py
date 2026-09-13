import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.db.base import async_session_factory
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import DEFAULT_TRAINING_REMINDER_HOUR
from app.domain.rules import TrainingReadiness, check_training_readiness

logger = logging.getLogger(__name__)

JOB_ID = "training_reminder"
# Не CronTrigger на фиксированный UTC-час (как send_weekly_reports/
# send_weekly_digest_reminder) — у каждого пользователя свой часовой пояс и
# свой выбранный час (training_reminder_hour), поэтому единственного момента
# "все сразу" не существует. Вместо этого — периодический опрос всех
# включивших уведомление: интервал короче часа, чтобы не пропустить нужный
# локальный час ни у одного часового пояса.
POLL_INTERVAL_MINUTES = 15


async def _send_training_reminders(session: AsyncSession, bot: Bot) -> int:
    sent = 0
    users_repo = UserRepository(session)
    workouts = WorkoutRepository(session)
    users = await users_repo.list_onboarded()

    for user in users:
        if not user.training_reminder_enabled or not user.timezone:
            continue
        try:
            local_now = datetime.now(ZoneInfo(user.timezone))
        except ZoneInfoNotFoundError:
            logger.warning(
                "training_reminder: invalid timezone %r for user %s", user.timezone, user.telegram_id,
            )
            continue

        reminder_hour = (
            user.training_reminder_hour
            if user.training_reminder_hour is not None
            else DEFAULT_TRAINING_REMINDER_HOUR
        )
        if local_now.hour != reminder_hour:
            continue
        if user.training_reminder_last_sent_date == local_now.date():
            continue

        history = await workouts.list_for_user(user.id)
        if not history:
            continue
        # UTC "сегодня", не local_now.date() — та же точка отсчёта, что и у
        # resolve_rest_day_notice/handle_start_workout (issue #94): готовность
        # к тренировке нигде в проекте не считается по локальному часовому
        # поясу пользователя, local_now здесь только для часа отправки и
        # анти-дублирования (training_reminder_last_sent_date).
        readiness = check_training_readiness(history[-1].performed_at.date(), datetime.now(UTC).date())
        if readiness.status == TrainingReadiness.TOO_EARLY:
            continue

        try:
            await bot.send_message(user.telegram_id, texts.TRAINING_REMINDER_TODAY)
        except TelegramAPIError:
            logger.warning(
                "training_reminder: failed to notify user %s", user.telegram_id, exc_info=True,
            )
            continue
        await users_repo.mark_training_reminder_sent(user.id, local_now.date())
        sent += 1
    return sent


async def send_training_reminders(bot: Bot, *, session: AsyncSession | None = None) -> None:
    """Проактивное push-уведомление "сегодня по плану тренировка" (issue
    #100) — зеркало resolve_rest_day_notice (app/bot/handlers/workout.py,
    issue #94) для противоположного случая: там статус показывается только
    при открытии бота (TOO_EARLY), здесь — push именно потому, что
    сформулировано в issue как "уведомление", не просто более заметный
    статус при следующем открытии.

    training_reminder_last_sent_date (локальная дата, не UTC) — без него
    опрос каждые POLL_INTERVAL_MINUTES отправил бы одно и то же уведомление
    несколько раз подряд, пока текущий локальный час совпадает с
    training_reminder_hour.

    session — тем же принципом, что send_weekly_digest_reminder
    (app/workers/weekly_digest.py): тесты передают свою сессию (тестовую
    БД), в бою здесь же открывается своя через async_session_factory —
    без инъекции воркер соединялся бы напрямую с DATABASE_URL из .env в
    обход тестовой БД."""
    if session is not None:
        sent = await _send_training_reminders(session, bot)
    else:
        async with async_session_factory() as db_session:
            sent = await _send_training_reminders(db_session, bot)

    if sent:
        logger.info("training_reminder: sent %s reminder(s)", sent)


def register(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    scheduler.add_job(
        send_training_reminders,
        IntervalTrigger(minutes=POLL_INTERVAL_MINUTES),
        id=JOB_ID,
        kwargs={"bot": bot},
    )
