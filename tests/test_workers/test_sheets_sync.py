import logging
from unittest.mock import MagicMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.services import sheets_export
from app.workers import sheets_sync as sheets_sync_module
from app.workers.sheets_sync import JOB_ID, SYNC_INTERVAL_MINUTES, register, sync_sheets


@pytest.fixture
def sheets_env_configured(monkeypatch):
    """GOOGLE_SHEETS_* заполнены — как на проде, где они остались в .env."""
    monkeypatch.setattr(settings, "google_sheets_spreadsheet_id", "prod-spreadsheet-id")
    monkeypatch.setattr(settings, "google_sheets_credentials_path", "/app/secrets/google-sheets-service-account.json")


def test_register_does_not_schedule_when_export_disabled(sheets_env_configured, caplog):
    """Релиз: выгрузка отключена (решение владельца 2026-10-16) — задача не
    планируется даже при заполненных GOOGLE_SHEETS_*, один лог об этом."""
    scheduler = AsyncIOScheduler()

    with caplog.at_level(logging.INFO, logger=sheets_sync_module.__name__):
        register(scheduler)

    assert scheduler.get_job(JOB_ID) is None
    disabled_logs = [r for r in caplog.records if "отключена" in r.getMessage()]
    assert len(disabled_logs) == 1


def test_bot_scheduler_has_no_sheets_job_when_export_disabled(sheets_env_configured):
    """Точка запуска бота (app/main.py::build_scheduler) — остальные воркеры
    на месте, синка Google Sheets нет."""
    from app.main import build_scheduler

    scheduler = build_scheduler(MagicMock(), MagicMock())

    job_ids = {job.id for job in scheduler.get_jobs()}
    assert JOB_ID not in job_ids
    assert job_ids  # остальные воркеры (robokassa, отчёты, напоминания) зарегистрированы


async def test_sync_sheets_sends_nothing_when_export_disabled(sheets_env_configured, monkeypatch):
    """Прямой вызов прохода (например, ручной запуск задачи) — no-op: ни
    клиента Google, ни сессии БД."""
    def _forbidden(*args, **kwargs):
        raise AssertionError("sync_sheets не должен ничего создавать при отключённой выгрузке")

    monkeypatch.setattr(sheets_sync_module, "GspreadSheetsClient", _forbidden)
    monkeypatch.setattr(sheets_sync_module, "async_session_factory", _forbidden)

    await sync_sheets()


def test_register_adds_job_with_expected_interval_when_enabled_in_code(monkeypatch):
    """Осознанное включение правкой кода — прежнее поведение планировщика."""
    monkeypatch.setattr(sheets_export, "SHEETS_EXPORT_ENABLED", True)
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
    monkeypatch.setattr(sheets_export, "SHEETS_EXPORT_ENABLED", True)
    monkeypatch.setattr(settings, "google_sheets_spreadsheet_id", "")
    monkeypatch.setattr(settings, "google_sheets_credentials_path", "")

    await sync_sheets()  # не должно бросить исключение или обратиться к БД/сети
