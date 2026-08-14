from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.workers.sheets_sync import JOB_ID, SYNC_INTERVAL_MINUTES, register, sync_sheets


def test_register_adds_job_with_expected_interval():
    scheduler = AsyncIOScheduler()

    register(scheduler)

    job = scheduler.get_job(JOB_ID)
    assert job is not None
    assert job.func is sync_sheets
    assert job.trigger.interval.total_seconds() == SYNC_INTERVAL_MINUTES * 60


async def test_sync_sheets_is_a_noop_when_not_configured(monkeypatch):
    """Пустые GOOGLE_SHEETS_SPREADSHEET_ID/GOOGLE_SHEETS_CREDENTIALS_PATH —
    тихий no-op (окружения без этих credentials, например тесты/локальная
    разработка, не должны падать)."""
    monkeypatch.setattr(settings, "google_sheets_spreadsheet_id", "")
    monkeypatch.setattr(settings, "google_sheets_credentials_path", "")

    await sync_sheets()  # не должно бросить исключение или обратиться к БД/сети
