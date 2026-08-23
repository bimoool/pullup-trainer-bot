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
from app.services.robokassa import RobokassaClient, RobokassaService

logger = logging.getLogger(__name__)

SYNC_INTERVAL_MINUTES = 5
JOB_ID = "robokassa_sync"


async def sync_robokassa_payments(bot: Bot) -> None:
    """Своя сессия, коммит по итогам прохода, уведомление пользователю при
    подтверждении.

    Без merchant_login/password_1/password_2 в конфиге список pending-заказов
    для этого провайдера всегда пуст (кнопка оплаты Робокассой скрыта, пока
    их нет — см. paywall_keyboard), так что воркер безопасно бездействует
    до появления реальных ключей."""
    async with async_session_factory() as session:
        client = RobokassaClient(
            merchant_login=settings.robokassa_merchant_login,
            password_1=settings.robokassa_password_1,
            password_2=settings.robokassa_password_2,
        )
        service = RobokassaService(session, client)
        users = UserRepository(session)

        async def _notify(payment: PendingPayment) -> None:
            user = await users.get_by_id(payment.user_id)
            if user is None:
                return
            try:
                await bot.send_message(user.telegram_id, texts.CARD_PAYMENT_CONFIRMED)
            except TelegramAPIError:
                logger.warning("robokassa_sync: failed to notify user %s", user.telegram_id, exc_info=True)
            else:
                # Раньше лога успеха не было вовсе — при диагностике первого
                # живого платежа доставку пришлось подтверждать вручную,
                # глядя в свой чат с ботом, поскольку "нет warning" не
                # доказывает "сообщение реально дошло" настолько же прямо,
                # как явная запись.
                logger.info("robokassa_sync: notified user %s of confirmed payment %s", user.telegram_id, payment.id)

        confirmed = await service.sync_pending_payments(now=datetime.now(UTC), on_confirmed=_notify)
        await session.commit()
    if confirmed:
        logger.info("robokassa_sync: confirmed %s payment(s)", confirmed)


def register(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    scheduler.add_job(
        sync_robokassa_payments, "interval", minutes=SYNC_INTERVAL_MINUTES, id=JOB_ID, kwargs={"bot": bot},
    )
