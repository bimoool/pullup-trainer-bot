import logging
from datetime import UTC, datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot import texts
from app.config import settings
from app.db.base import async_session_factory
from app.db.models import PendingPayment
from app.db.repositories.users import UserRepository
from app.services.tribute import TributeClient, TributeService

logger = logging.getLogger(__name__)

SYNC_INTERVAL_MINUTES = 5
JOB_ID = "tribute_sync"


async def sync_tribute_payments(bot: Bot) -> None:
    """Один проход опроса — открывает свою сессию (это фоновая задача, не
    запрос, к текущей сессии привязываться не к чему), коммитит по итогам.

    Раньше воркер молчал: подписка продлевалась в БД, но пользователь об
    этом не узнавал, пока сам не проверял бота — теперь при подтверждении
    отправляем сообщение."""
    async with async_session_factory() as session:
        client = TributeClient(settings.tribute_api_key)
        service = TributeService(session, client)
        users = UserRepository(session)

        async def _notify(payment: PendingPayment) -> None:
            user = await users.get_by_id(payment.user_id)
            if user is None:
                return
            try:
                await bot.send_message(user.telegram_id, texts.TRIBUTE_PAYMENT_CONFIRMED)
            except TelegramAPIError:
                logger.warning("tribute_sync: failed to notify user %s", user.telegram_id, exc_info=True)

        confirmed = await service.sync_pending_payments(now=datetime.now(UTC), on_confirmed=_notify)
        await session.commit()
    if confirmed:
        logger.info("tribute_sync: confirmed %s payment(s)", confirmed)


def register(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    scheduler.add_job(
        sync_tribute_payments, "interval", minutes=SYNC_INTERVAL_MINUTES, id=JOB_ID, kwargs={"bot": bot},
    )
