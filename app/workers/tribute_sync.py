import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.db.base import async_session_factory
from app.services.tribute import TributeClient, TributeService

logger = logging.getLogger(__name__)

SYNC_INTERVAL_MINUTES = 5
JOB_ID = "tribute_sync"


async def sync_tribute_payments() -> None:
    """Один проход опроса — открывает свою сессию (это фоновая задача, не
    запрос, к текущей сессии привязываться не к чему), коммитит по итогам."""
    async with async_session_factory() as session:
        client = TributeClient(settings.tribute_api_key)
        service = TributeService(session, client)
        confirmed = await service.sync_pending_payments(now=datetime.now(UTC))
        await session.commit()
    if confirmed:
        logger.info("tribute_sync: confirmed %s payment(s)", confirmed)


def register(scheduler: AsyncIOScheduler) -> None:
    scheduler.add_job(sync_tribute_payments, "interval", minutes=SYNC_INTERVAL_MINUTES, id=JOB_ID)
