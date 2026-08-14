import asyncio
import logging
from typing import Protocol

import gspread
from gspread.exceptions import APIError, WorksheetNotFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Event, User
from app.db.repositories.events import EventRepository
from app.db.repositories.sheets_sync_state import SheetsSyncStateRepository
from app.db.repositories.users import UserRepository

logger = logging.getLogger(__name__)

EVENTS_SHEET_TITLE = "events"
USERS_SHEET_TITLE = "users"

EVENTS_HEADER = ["id", "user_id", "telegram_id", "event_type", "payload", "created_at"]
USERS_HEADER = [
    "id", "telegram_id", "username", "onboarding_completed_at",
    "subscription_status", "subscription_expires_at", "coins_balance", "created_at",
]

# Батч-запись (не по одной строке за раз, см. ROADMAP Часть 6) — но и не
# бесконечный один запрос: при большом бэклоге (первый запуск воркера на
# проекте с историей) разбиваем на чанки, чтобы не упереться в лимит
# размера одного request body Google Sheets API.
MAX_ROWS_PER_REQUEST = 500

_RETRYABLE_STATUS = 429
_MAX_RETRIES = 5
_RETRY_BASE_DELAY_SECONDS = 2.0


def event_to_row(event: Event, *, telegram_id: int | None) -> list[str]:
    return [
        str(event.id),
        str(event.user_id),
        str(telegram_id) if telegram_id is not None else "",
        event.event_type,
        _payload_to_text(event.payload),
        event.created_at.isoformat(),
    ]


def user_to_row(user: User) -> list[str]:
    return [
        str(user.id),
        str(user.telegram_id),
        user.username or "",
        user.onboarding_completed_at.isoformat() if user.onboarding_completed_at else "",
        user.subscription_status.value,
        user.subscription_expires_at.isoformat() if user.subscription_expires_at else "",
        str(user.coins_balance),
        user.created_at.isoformat(),
    ]


def _payload_to_text(payload: dict) -> str:
    if not payload:
        return ""
    return ", ".join(f"{key}={value}" for key, value in payload.items())


class SheetsClientProtocol(Protocol):
    """Форма, против которой тестируется воркер (app/workers/sheets_sync.py)
    через фейковую реализацию — та же схема, что и TributeClientProtocol
    (app/services/tribute.py), без обращения к реальному Google API."""

    async def append_rows(self, sheet_title: str, header: list[str], rows: list[list[str]]) -> None: ...

    async def replace_all_rows(self, sheet_title: str, header: list[str], rows: list[list[str]]) -> None: ...


class GspreadSheetsClient:
    """Тонкая обёртка над gspread — без бизнес-логики, только транспорт.

    gspread синхронный (блокирующие HTTP-запросы под капотом) — весь
    реальный ввод-вывод уходит в отдельный поток через asyncio.to_thread,
    чтобы не подвешивать event loop бота (тот же процесс, что и long
    polling aiogram) на время сетевого запроса к Google.

    Открытие клиента/таблицы — по одному разу за вызов sync_sheets()
    (создаётся заново в каждом цикле воркера, раз в 5 минут — то же самое
    решение, что и в TributeClient, а не держать один долгоживущий
    объект и думать про истечение токена)."""

    def __init__(self, *, credentials_path: str, spreadsheet_id: str) -> None:
        self._credentials_path = credentials_path
        self._spreadsheet_id = spreadsheet_id

    async def append_rows(self, sheet_title: str, header: list[str], rows: list[list[str]]) -> None:
        if not rows:
            return
        worksheet = await asyncio.to_thread(self._get_or_create_worksheet, sheet_title, header)
        for chunk in _chunk(rows, MAX_ROWS_PER_REQUEST):
            await _call_with_retry(worksheet.append_rows, chunk)

    async def replace_all_rows(self, sheet_title: str, header: list[str], rows: list[list[str]]) -> None:
        """Срез, не история (см. app/workers/sheets_sync.py) — лист users
        полностью перезаписывается на каждом синке, не дополняется."""
        worksheet = await asyncio.to_thread(self._get_or_create_worksheet, sheet_title, header)
        await _call_with_retry(worksheet.clear)
        all_rows = [header, *rows]
        for chunk in _chunk(all_rows, MAX_ROWS_PER_REQUEST):
            await _call_with_retry(worksheet.append_rows, chunk)

    def _get_or_create_worksheet(self, sheet_title: str, header: list[str]) -> gspread.Worksheet:
        client = gspread.service_account(filename=self._credentials_path)
        spreadsheet = client.open_by_key(self._spreadsheet_id)
        try:
            return spreadsheet.worksheet(sheet_title)
        except WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(title=sheet_title, rows=1000, cols=len(header))
            worksheet.append_rows([header])
            return worksheet


def _chunk(rows: list[list[str]], size: int) -> list[list[list[str]]]:
    return [rows[i:i + size] for i in range(0, len(rows), size)]


async def _call_with_retry(func, *args) -> None:
    """429 (квота Google Sheets API) — не наша ошибка, повторяем с
    задержкой вместо падения всего цикла синка. Другие APIError (неверный
    ID таблицы, нет доступа у сервисного аккаунта) пробрасываются сразу —
    ретраить их бессмысленно, это конфигурационная проблема."""
    for attempt in range(_MAX_RETRIES):
        try:
            await asyncio.to_thread(func, *args)
            return
        except APIError as error:
            status = getattr(error.response, "status_code", None)
            if status != _RETRYABLE_STATUS or attempt == _MAX_RETRIES - 1:
                raise
            delay = _RETRY_BASE_DELAY_SECONDS * (2**attempt)
            logger.warning("sheets_export: 429 from Sheets API, retrying in %.1fs (attempt %s)", delay, attempt + 1)
            await asyncio.sleep(delay)


class SheetsExportService:
    """Оркестрация: сколько выгрузить и откуда взять данные — воркер
    (app/workers/sheets_sync.py) только открывает сессию и вызывает sync().
    Та же структура, что и TributeService (app/services/tribute.py):
    репозитории внутри, внешний клиент — через протокол, не завязана на
    конкретную реализацию (тестируется фейковым клиентом)."""

    def __init__(self, session: AsyncSession, client: SheetsClientProtocol) -> None:
        self._session = session
        self._events = EventRepository(session)
        self._users = UserRepository(session)
        self._cursor = SheetsSyncStateRepository(session)
        self._client = client

    async def sync(self, *, events_page_size: int = 1000) -> tuple[int, int]:
        """Один полный цикл — events постранично (только новые с прошлого
        синка, курсор коммитится после каждой успешно выгруженной
        страницы, чтобы сбой посреди большого бэклога не терял уже
        выгруженный прогресс), затем users целиком как срез (не история —
        полная перезапись листа на каждом синке). Возвращает (число
        выгруженных событий, число пользователей в срезе)."""
        all_users = await self._users.list_all()
        telegram_id_by_user_id = {user.id: user.telegram_id for user in all_users}

        events_synced = 0
        while True:
            last_id = await self._cursor.get_last_event_id()
            events = await self._events.list_since(last_id, limit=events_page_size)
            if not events:
                break

            rows = [
                event_to_row(event, telegram_id=telegram_id_by_user_id.get(event.user_id))
                for event in events
            ]
            await self._client.append_rows(EVENTS_SHEET_TITLE, EVENTS_HEADER, rows)
            await self._cursor.set_last_event_id(events[-1].id)
            await self._session.commit()
            events_synced += len(events)

            if len(events) < events_page_size:
                break

        user_rows = [user_to_row(user) for user in all_users]
        await self._client.replace_all_rows(USERS_SHEET_TITLE, USERS_HEADER, user_rows)
        return events_synced, len(all_users)
