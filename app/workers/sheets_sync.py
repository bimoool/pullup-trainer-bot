import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.db.base import async_session_factory
from app.services.sheets_export import GspreadSheetsClient, SheetsExportService

logger = logging.getLogger(__name__)

SYNC_INTERVAL_MINUTES = 5
JOB_ID = "sheets_sync"


async def sync_sheets() -> None:
    """Один проход выгрузки в Google Sheets (ROADMAP Часть 6 «Аналитика»).

    Не настроено (нет ID таблицы или пути к ключу сервисного аккаунта) —
    тихий no-op, не ошибка: фича опциональна, окружения без нужных
    credentials (локальная разработка, CI) не должны падать из-за их
    отсутствия — та же логика, что и у остальных опциональных интеграций."""
    if not settings.google_sheets_spreadsheet_id or not settings.google_sheets_credentials_path:
        return

    client = GspreadSheetsClient(
        credentials_path=settings.google_sheets_credentials_path,
        spreadsheet_id=settings.google_sheets_spreadsheet_id,
    )
    async with async_session_factory() as session:
        service = SheetsExportService(session, client)
        events_synced, users_count = await service.sync()

    if events_synced:
        logger.info("sheets_sync: synced %s new event(s), %s user(s) in snapshot", events_synced, users_count)


def register(scheduler: AsyncIOScheduler) -> None:
    scheduler.add_job(sync_sheets, "interval", minutes=SYNC_INTERVAL_MINUTES, id=JOB_ID)
