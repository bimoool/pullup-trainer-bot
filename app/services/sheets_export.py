import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

import gspread
from gspread.exceptions import APIError, WorksheetNotFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Achievement, BlockType, Coin, Event, SubscriptionStatus, User
from app.db.models import ElectiveWorkout as ElectiveWorkoutModel
from app.db.models import EquipmentItem as EquipmentItemModel
from app.db.models import Subscription as SubscriptionModel
from app.db.models import Workout as WorkoutModel
from app.db.repositories.achievements import AchievementRepository
from app.db.repositories.coins import CoinRepository
from app.db.repositories.elective_workouts import ElectiveWorkoutRepository
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.events import EventRepository
from app.db.repositories.sheets_sync_state import SheetsSyncStateRepository
from app.db.repositories.subscriptions import SubscriptionRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository

logger = logging.getLogger(__name__)

EVENTS_SHEET_TITLE = "events"
USERS_SHEET_TITLE = "users"
WORKOUTS_SHEET_TITLE = "workouts"
SUBSCRIPTIONS_SHEET_TITLE = "subscriptions"
COINS_SHEET_TITLE = "coins"
ACHIEVEMENTS_SHEET_TITLE = "achievements"
EQUIPMENT_ITEMS_SHEET_TITLE = "equipment_items"

ALL_SHEET_TITLES = [
    EVENTS_SHEET_TITLE, USERS_SHEET_TITLE, WORKOUTS_SHEET_TITLE,
    SUBSCRIPTIONS_SHEET_TITLE, COINS_SHEET_TITLE, ACHIEVEMENTS_SHEET_TITLE, EQUIPMENT_ITEMS_SHEET_TITLE,
]

EVENTS_HEADER = ["id", "user_id", "telegram_id", "event_type", "payload", "created_at"]
USERS_HEADER = [
    "id", "telegram_id", "username", "onboarding_completed_at", "onboarding_stage",
    "subscription_status", "subscription_expires_at", "coins_balance", "created_at",
]
# username рядом с telegram_id (не вместо) — реальный пробел с прямой
# сверки данных автором: без него приходилось вручную сопоставлять с
# листом users, чтобы понять, чьи это строки. Один блок одной тренировки/
# факультатива — не вся тренировка целиком, так проще фильтровать и
# сравнивать блок A и блок B по отдельности в самой таблице. entry_type
# различает происхождение (live/backdated/free/elective_<тип>) — у
# структурных тренировок 2 строки (блок A и B), у свободных — 1 (пустой
# блок B — заглушка на уровне схемы, в лог не идёт), у факультативов — 1
# (block="-", target_before/after не применимы, они вне прогрессии).
WORKOUTS_HEADER = [
    "id", "entry_type", "user_id", "telegram_id", "username", "performed_at", "block",
    "equipment", "equipment_value", "reps", "max_reps",
    "target_before", "target_after", "volume", "comment",
]
SUBSCRIPTIONS_HEADER = [
    "id", "user_id", "telegram_id", "username", "status", "source",
    "started_at", "ends_at", "payment_reference", "created_at",
]
COINS_HEADER = [
    "id", "user_id", "telegram_id", "username", "amount", "reason", "related_achievement_id", "created_at",
]
ACHIEVEMENTS_HEADER = ["id", "user_id", "telegram_id", "username", "code", "unlocked_at", "context"]
EQUIPMENT_ITEMS_HEADER = ["id", "user_id", "telegram_id", "name", "resistance_kg", "position", "created_at"]

# Заморозка шапки + жирный/подсвеченный заголовок — применяются каждый
# цикл синка безусловно (идемпотентно, побочек нет). Базовый фильтр —
# только если на листе его ещё нет (см. GspreadSheetsClient.
# ensure_sheet_formatting): применять его безусловно каждые 5 минут стирало
# бы условия отбора, которые Кирилл сам настроит внутри фильтра в
# интерфейсе — сам факт наличия фильтра идемпотентен, а его критерии нет.
_HEADER_BACKGROUND_COLOR = {"red": 0.85, "green": 0.85, "blue": 0.85}

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
        _opt(telegram_id),
        event.event_type,
        _payload_to_text(event.payload),
        event.created_at.isoformat(),
    ]


def _onboarding_stage(user: User) -> str:
    """Грубая, но бесплатная оценка стадии воронки — только по уже
    загруженным полям User (без дополнительных запросов на baseline/
    первую тренировку, это можно досчитать вручную по листу workouts,
    если понадобится точнее)."""
    if user.onboarding_completed_at is None:
        profile_fields = (user.weight_kg, user.height_cm, user.gender, user.birth_date, user.timezone)
        filled = sum(field is not None for field in profile_fields)
        return "анкета не начата" if filled == 0 else f"анкета в процессе ({filled}/5)"
    if user.subscription_status == SubscriptionStatus.NONE:
        return "анкета завершена, без подписки"
    return f"анкета завершена, подписка: {user.subscription_status.value}"


def user_to_row(user: User) -> list[str]:
    return [
        str(user.id),
        str(user.telegram_id),
        user.username or "",
        user.onboarding_completed_at.isoformat() if user.onboarding_completed_at else "",
        _onboarding_stage(user),
        user.subscription_status.value,
        user.subscription_expires_at.isoformat() if user.subscription_expires_at else "",
        str(user.coins_balance),
        user.created_at.isoformat(),
    ]


def workout_to_rows(workout: WorkoutModel, *, telegram_id: int | None, username: str | None) -> list[list[str]]:
    entry_type = "free" if workout.is_free_entry else ("live" if workout.participates_in_cascade else "backdated")
    rows = []
    for block in sorted(workout.blocks, key=lambda b: b.block_type.value):
        if workout.is_free_entry and block.block_type == BlockType.B:
            continue  # заглушка на уровне схемы (record_free_workout) — в лог не идёт
        rows.append([
            str(workout.id), entry_type, str(workout.user_id), _opt(telegram_id), _opt(username),
            workout.performed_at.isoformat(), block.block_type.value,
            block.equipment_type.value, _opt(block.equipment_value),
            ", ".join(str(r) for r in block.working_reps), str(block.max_reps),
            str(block.target_before), str(block.target_after),
            str(sum(block.working_reps) + block.max_reps),
            workout.comment or "",
        ])
    return rows


def elective_to_row(elective: ElectiveWorkoutModel, *, telegram_id: int | None, username: str | None) -> list[str]:
    return [
        str(elective.id), f"elective_{elective.elective_type.value}", str(elective.user_id),
        _opt(telegram_id), _opt(username),
        elective.performed_at.isoformat(), "-",
        elective.equipment_type.value, _opt(elective.equipment_value),
        ", ".join(str(r) for r in elective.reps_sequence) if elective.reps_sequence else "",
        "",  # max_reps — не применимо, факультативы не выделяют отдельный подход на максимум
        "", "",  # target_before/after — вне прогрессии, не применимо
        str(elective.total_reps),
        "",
    ]


def subscription_to_row(subscription: SubscriptionModel, *, telegram_id: int | None, username: str | None) -> list[str]:
    return [
        str(subscription.id), str(subscription.user_id), _opt(telegram_id), _opt(username),
        subscription.status.value, subscription.source.value,
        subscription.started_at.isoformat(), subscription.ends_at.isoformat(),
        subscription.payment_reference or "", subscription.created_at.isoformat(),
    ]


def coin_to_row(coin: Coin, *, telegram_id: int | None, username: str | None) -> list[str]:
    return [
        str(coin.id), str(coin.user_id), _opt(telegram_id), _opt(username), str(coin.amount), coin.reason.value,
        _opt(coin.related_achievement_id), coin.created_at.isoformat(),
    ]


def achievement_to_row(achievement: Achievement, *, telegram_id: int | None, username: str | None) -> list[str]:
    return [
        str(achievement.id), str(achievement.user_id), _opt(telegram_id), _opt(username), achievement.code,
        achievement.unlocked_at.isoformat(), _payload_to_text(achievement.context or {}),
    ]


def equipment_item_to_row(item: EquipmentItemModel, *, telegram_id: int | None) -> list[str]:
    return [
        str(item.id), str(item.user_id), _opt(telegram_id), item.name,
        _opt(item.resistance_kg), str(item.position), item.created_at.isoformat(),
    ]


def _opt(value: object) -> str:
    return "" if value is None else str(value)


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

    async def ensure_sheet_formatting(self, sheet_titles: list[str]) -> None: ...


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
        """Срез, не история (users/equipment_items) — лист полностью
        перезаписывается на каждом синке, не дополняется."""
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

    async def ensure_sheet_formatting(self, sheet_titles: list[str]) -> None:
        """Закреплённая шапка + жирный/подсвеченный заголовок + базовый
        фильтр — программно, идемпотентно, одним batchUpdate на ВСЕ листы
        сразу за цикл синка (не по запросу на лист). Листы, которых ещё
        нет (WorksheetNotFound на этот sheet_title не возникает — просто
        не найдётся в fetch_sheet_metadata), тихо пропускаются:
        отформатируются на одном из следующих циклов, когда появятся."""
        spreadsheet, requests = await asyncio.to_thread(self._build_formatting_requests, sheet_titles)
        if not requests:
            return
        await _call_with_retry(spreadsheet.batch_update, {"requests": requests})

    def _build_formatting_requests(self, sheet_titles: list[str]) -> tuple[gspread.Spreadsheet, list[dict]]:
        client = gspread.service_account(filename=self._credentials_path)
        spreadsheet = client.open_by_key(self._spreadsheet_id)
        metadata = spreadsheet.fetch_sheet_metadata()
        requests: list[dict] = []
        for sheet in metadata.get("sheets", []):
            properties = sheet.get("properties", {})
            if properties.get("title") not in sheet_titles:
                continue
            sheet_id = properties["sheetId"]
            requests.append(_freeze_header_request(sheet_id))
            requests.append(_bold_header_request(sheet_id))
            # Только если фильтра ещё нет — см. комментарий у ALL_SHEET_TITLES:
            # безусловное переприменение стирало бы условия отбора внутри
            # фильтра, которые владелец таблицы сам настроит в интерфейсе.
            if "basicFilter" not in sheet:
                requests.append(_basic_filter_request(sheet_id))
        return spreadsheet, requests


def _freeze_header_request(sheet_id: int) -> dict:
    return {
        "updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        },
    }


def _basic_filter_request(sheet_id: int) -> dict:
    # GridRange без явных границ строк/колонок = весь лист целиком.
    return {"setBasicFilter": {"filter": {"range": {"sheetId": sheet_id}}}}


def _bold_header_request(sheet_id: int) -> dict:
    return {
        "repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {
                "userEnteredFormat": {
                    "textFormat": {"bold": True},
                    "backgroundColor": _HEADER_BACKGROUND_COLOR,
                },
            },
            "fields": "userEnteredFormat(textFormat,backgroundColor)",
        },
    }


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


@dataclass(frozen=True)
class SyncResult:
    events: int
    workouts: int
    electives: int
    subscriptions: int
    coins: int
    achievements: int
    users: int
    equipment_items: int


_T = TypeVar("_T")


class SheetsExportService:
    """Оркестрация: сколько выгрузить и откуда взять данные — воркер
    (app/workers/sheets_sync.py) только открывает сессию и вызывает sync().
    Та же структура, что и TributeService (app/services/tribute.py):
    репозитории внутри, внешний клиент — через протокол, не завязана на
    конкретную реализацию (тестируется фейковым клиентом).

    events/workouts/electives/subscriptions/coins/achievements —
    инкремент по курсору (SheetsSyncStateRepository), history растёт, не
    перезаписывается; workouts и electives пишут в ОДИН лист ("workouts")
    каждый со своим курсором — разные источники, общий формат строки.
    users/equipment_items — полный срез на каждом синке (не история)."""

    def __init__(self, session: AsyncSession, client: SheetsClientProtocol) -> None:
        self._session = session
        self._events = EventRepository(session)
        self._workouts = WorkoutRepository(session)
        self._electives = ElectiveWorkoutRepository(session)
        self._subscriptions = SubscriptionRepository(session)
        self._coins = CoinRepository(session)
        self._achievements = AchievementRepository(session)
        self._users = UserRepository(session)
        self._equipment_items = EquipmentItemRepository(session)
        self._cursor = SheetsSyncStateRepository(session)
        self._client = client

    async def sync(self, *, page_size: int = 1000) -> SyncResult:
        all_users = await self._users.list_all()
        telegram_id_by_user_id = {user.id: user.telegram_id for user in all_users}
        username_by_user_id = {user.id: user.username for user in all_users}

        def telegram_id_of(item) -> int | None:
            return telegram_id_by_user_id.get(item.user_id)

        def username_of(item) -> str | None:
            return username_by_user_id.get(item.user_id)

        events = await self._sync_incremental(
            sheet_title=EVENTS_SHEET_TITLE, header=EVENTS_HEADER, page_size=page_size,
            get_cursor=self._cursor.get_last_event_id, set_cursor=self._cursor.set_last_event_id,
            fetch_page=self._events.list_since,
            to_rows=lambda item: [event_to_row(item, telegram_id=telegram_id_of(item))],
        )
        workouts = await self._sync_incremental(
            sheet_title=WORKOUTS_SHEET_TITLE, header=WORKOUTS_HEADER, page_size=page_size,
            get_cursor=self._cursor.get_last_workout_id, set_cursor=self._cursor.set_last_workout_id,
            fetch_page=self._workouts.list_since,
            to_rows=lambda item: workout_to_rows(item, telegram_id=telegram_id_of(item), username=username_of(item)),
        )
        electives = await self._sync_incremental(
            sheet_title=WORKOUTS_SHEET_TITLE, header=WORKOUTS_HEADER, page_size=page_size,
            get_cursor=self._cursor.get_last_elective_id, set_cursor=self._cursor.set_last_elective_id,
            fetch_page=self._electives.list_since,
            to_rows=lambda item: [elective_to_row(item, telegram_id=telegram_id_of(item), username=username_of(item))],
        )
        subscriptions = await self._sync_incremental(
            sheet_title=SUBSCRIPTIONS_SHEET_TITLE, header=SUBSCRIPTIONS_HEADER, page_size=page_size,
            get_cursor=self._cursor.get_last_subscription_id, set_cursor=self._cursor.set_last_subscription_id,
            fetch_page=self._subscriptions.list_since,
            to_rows=lambda item: [
                subscription_to_row(item, telegram_id=telegram_id_of(item), username=username_of(item)),
            ],
        )
        coins = await self._sync_incremental(
            sheet_title=COINS_SHEET_TITLE, header=COINS_HEADER, page_size=page_size,
            get_cursor=self._cursor.get_last_coin_id, set_cursor=self._cursor.set_last_coin_id,
            fetch_page=self._coins.list_since,
            to_rows=lambda item: [coin_to_row(item, telegram_id=telegram_id_of(item), username=username_of(item))],
        )
        achievements = await self._sync_incremental(
            sheet_title=ACHIEVEMENTS_SHEET_TITLE, header=ACHIEVEMENTS_HEADER, page_size=page_size,
            get_cursor=self._cursor.get_last_achievement_id, set_cursor=self._cursor.set_last_achievement_id,
            fetch_page=self._achievements.list_since,
            to_rows=lambda item: [
                achievement_to_row(item, telegram_id=telegram_id_of(item), username=username_of(item)),
            ],
        )

        user_rows = [user_to_row(user) for user in all_users]
        await self._client.replace_all_rows(USERS_SHEET_TITLE, USERS_HEADER, user_rows)

        equipment_items = await self._equipment_items.list_all()
        equipment_rows = [equipment_item_to_row(item, telegram_id=telegram_id_of(item)) for item in equipment_items]
        await self._client.replace_all_rows(EQUIPMENT_ITEMS_SHEET_TITLE, EQUIPMENT_ITEMS_HEADER, equipment_rows)

        # Заморозка шапки/фильтр/жирный заголовок — каждый цикл, одним
        # batchUpdate на все листы разом (см. GspreadSheetsClient.
        # ensure_sheet_formatting). Не только для новых листов — самоисправляет
        # и уже существующие в проде, без ручного вмешательства.
        await self._client.ensure_sheet_formatting(ALL_SHEET_TITLES)

        return SyncResult(
            events=events, workouts=workouts, electives=electives,
            subscriptions=subscriptions, coins=coins, achievements=achievements,
            users=len(all_users), equipment_items=len(equipment_items),
        )

    async def _sync_incremental(
        self,
        *,
        sheet_title: str,
        header: list[str],
        page_size: int,
        get_cursor: Callable[[], Awaitable[int]],
        set_cursor: Callable[[int], Awaitable[None]],
        fetch_page: Callable[..., Awaitable[list[_T]]],
        to_rows: Callable[[_T], list[list[str]]],
    ) -> int:
        """Один инкрементальный источник — постранично, только новое с
        прошлого синка, курсор коммитится после каждой успешно
        выгруженной страницы (сбой посреди большого бэклога не теряет уже
        выгруженный прогресс). item.id (последний в странице) — новое
        значение курсора; постраничность считается по числу ИСХОДНЫХ
        записей (len(page)), не по числу строк на выходе (workouts даёт
        1-2 строки на запись, окончание страницы должно ориентироваться на
        реальный конец источника, не на объём вывода)."""
        synced = 0
        while True:
            cursor = await get_cursor()
            page = await fetch_page(cursor, limit=page_size)
            if not page:
                break

            rows = [row for item in page for row in to_rows(item)]
            await self._client.append_rows(sheet_title, header, rows)
            await set_cursor(page[-1].id)
            await self._session.commit()
            synced += len(page)

            if len(page) < page_size:
                break
        return synced
