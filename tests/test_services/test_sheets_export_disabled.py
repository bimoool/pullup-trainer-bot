"""Выгрузка в Google Sheets отключена в релизе (решение владельца 2026-10-16:
персональные данные к стороннему иностранному обработчику без политики
конфиденциальности/согласия). Тесты доказывают, что ни один путь не
отправит данные даже при заполненных GOOGLE_SHEETS_* в окружении."""

import gspread
import pytest

from app.config import settings
from app.services import sheets_export
from app.services.sheets_export import (
    GspreadSheetsClient,
    SheetsExportDisabledError,
    SheetsExportService,
    ensure_sheets_export_enabled,
)


@pytest.fixture
def sheets_env_configured(monkeypatch):
    """GOOGLE_SHEETS_* заполнены — как на проде, где они остались в .env."""
    monkeypatch.setattr(settings, "google_sheets_spreadsheet_id", "prod-spreadsheet-id")
    monkeypatch.setattr(settings, "google_sheets_credentials_path", "/app/secrets/google-sheets-service-account.json")


@pytest.fixture
def no_google_network(monkeypatch):
    def _forbidden(*args, **kwargs):
        raise AssertionError("обращение к Google API при отключённой выгрузке")

    monkeypatch.setattr(gspread, "service_account", _forbidden)
    monkeypatch.setattr(sheets_export.gspread, "service_account", _forbidden)


def test_release_build_has_sheets_export_disabled():
    """Включение — только осознанной правкой кода, не переменной окружения."""
    assert sheets_export.SHEETS_EXPORT_ENABLED is False
    assert not any("sheets_export_enabled" in name for name in type(settings).model_fields)


def test_ensure_sheets_export_enabled_refuses():
    with pytest.raises(SheetsExportDisabledError):
        ensure_sheets_export_enabled()


def test_gspread_client_refuses_to_construct(sheets_env_configured, no_google_network):
    with pytest.raises(SheetsExportDisabledError):
        GspreadSheetsClient(
            credentials_path=settings.google_sheets_credentials_path,
            spreadsheet_id=settings.google_sheets_spreadsheet_id,
        )


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def append_rows(self, sheet_title, header, rows) -> None:
        self.calls.append(f"append:{sheet_title}")

    async def replace_all_rows(self, sheet_title, header, rows) -> None:
        self.calls.append(f"replace:{sheet_title}")

    async def ensure_sheet_structure(self, headers_by_sheet) -> None:
        self.calls.append("ensure_structure")


async def test_export_service_refuses_to_send(session, user, sheets_env_configured):
    """Даже с уже готовым клиентом (как в scripts/backfill_sheets_username.py)
    sync() ничего не читает и не отправляет — клиент не получает ни одного вызова."""
    client = _RecordingClient()
    service = SheetsExportService(session, client)

    with pytest.raises(SheetsExportDisabledError):
        await service.sync()

    assert client.calls == []
