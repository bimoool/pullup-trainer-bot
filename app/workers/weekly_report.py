import logging
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.bot import texts
from app.bot.formatting import format_weekly_summary
from app.db.base import async_session_factory
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.reports import weekly_summary

logger = logging.getLogger(__name__)

JOB_ID = "weekly_report"


async def send_weekly_reports(bot: Bot) -> None:
    """Раз в неделю (Часть 5 респека) — сводка только тем, у кого была хотя
    бы одна тренировка за неделю: молчаливым пользователям слать нечего,
    а спамить пустым отчётом только раздражает."""
    now = datetime.now(UTC)
    week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)

    sent = 0
    async with async_session_factory() as session:
        users = await UserRepository(session).list_onboarded()
        workouts = WorkoutRepository(session)

        for user in users:
            records = await workouts.list_records_for_user(user.id)
            this_week = [r for r in records if r.performed_at >= week_ago]
            if not this_week:
                continue
            previous_week = [r for r in records if two_weeks_ago <= r.performed_at < week_ago]
            previous_week_volume = sum(r.block_a.log.volume + r.block_b.log.volume for r in previous_week)

            summary = weekly_summary(this_week, previous_week_volume)
            text = f"{texts.WEEKLY_REPORT_HEADER}\n\n{format_weekly_summary(summary)}"
            try:
                await bot.send_message(user.telegram_id, text)
                sent += 1
            except TelegramAPIError:
                logger.warning("weekly_report: failed to notify user %s", user.telegram_id, exc_info=True)

    if sent:
        logger.info("weekly_report: sent %s report(s)", sent)


def register(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    # Понедельник, 09:00 UTC — часовой пояс пользователя учитывается только
    # для напоминаний о самой тренировке (отдельная, ещё не реализованная
    # задача), не для этой сводки.
    scheduler.add_job(
        send_weekly_reports, CronTrigger(day_of_week="mon", hour=9), id=JOB_ID, kwargs={"bot": bot},
    )
