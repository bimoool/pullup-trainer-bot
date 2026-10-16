import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.db.base import async_session_factory
from app.services import sheets_export
from app.services.sheets_export import GspreadSheetsClient, SheetsExportService

logger = logging.getLogger(__name__)

SYNC_INTERVAL_MINUTES = 5
JOB_ID = "sheets_sync"


async def sync_sheets() -> None:
    """Один проход выгрузки в Google Sheets (ROADMAP Часть 6 «Аналитика»).

    Не настроено (нет ID таблицы или пути к ключу сервисного аккаунта) —
    тихий no-op, не ошибка: фича опциональна, окружения без нужных
    credentials (локальная разработка, CI) не должны падать из-за их
    отсутствия — та же логика, что и у остальных опциональных интеграций.

    Экспорт отключён в релизе (sheets_export.SHEETS_EXPORT_ENABLED=False) —
    no-op независимо от GOOGLE_SHEETS_* в окружении."""
    if not sheets_export.SHEETS_EXPORT_ENABLED:
        return
    if not settings.google_sheets_spreadsheet_id or not settings.google_sheets_credentials_path:
        return

    client = GspreadSheetsClient(
        credentials_path=settings.google_sheets_credentials_path,
        spreadsheet_id=settings.google_sheets_spreadsheet_id,
    )
    async with async_session_factory() as session:
        service = SheetsExportService(session, client)
        result = await service.sync()

    incremental_total = (
        result.events + result.workouts + result.electives
        + result.subscriptions + result.coins + result.achievements + result.baselines
    )
    if incremental_total:
        logger.info(
            "sheets_sync: events=%s workouts=%s electives=%s subscriptions=%s coins=%s achievements=%s baselines=%s "
            "(users=%s, equipment_items=%s in snapshot)",
            result.events, result.workouts, result.electives,
            result.subscriptions, result.coins, result.achievements, result.baselines,
            result.users, result.equipment_items,
        )


def register(scheduler: AsyncIOScheduler) -> None:
    """Выгрузка отключена в релизе (см. sheets_export.SHEETS_EXPORT_ENABLED) —
    задача не планируется вовсе, а не планируется-и-молчит: в процессе бота
    нет ни одного пути, который дойдёт до Google API. Вызывается один раз из
    app/main.py::build_scheduler — отсюда одна строка лога на старт процесса."""
    if not sheets_export.SHEETS_EXPORT_ENABLED:
        logger.info(
            "sheets_sync: выгрузка в Google Sheets отключена в релизе (SHEETS_EXPORT_ENABLED=False) — "
            "задача не запланирована, данные не отправляются; GOOGLE_SHEETS_* игнорируются",
        )
        return
    scheduler.add_job(sync_sheets, "interval", minutes=SYNC_INTERVAL_MINUTES, id=JOB_ID)
