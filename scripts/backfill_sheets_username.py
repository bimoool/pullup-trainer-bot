"""Разовый скрипт бэкфилла username в исторических строках Google Sheets
(пакет #7, ревизия 3) — НЕ часть постоянной логики воркера, запускается
вручную один раз, после чего может быть удалён из репозитория.

Диагноз: до добавления колонки username в WORKOUTS_HEADER/EVENTS_HEADER/
SUBSCRIPTIONS_HEADER/COINS_HEADER/ACHIEVEMENTS_HEADER воркер уже дописал
в эти листы историю строк БЕЗ username (старая форма строки, на одну
колонку короче). Заголовок листов теперь чинится автоматически
(ensure_sheet_structure), но воркер только ДОПИСЫВАЕТ новые строки —
существующие никогда не трогает. В результате все строки, записанные до
этого пакета, читаются под неправильными подписями колонок: всё, что
идёт после telegram_id, сдвинуто на одну колонку влево относительно
актуального заголовка.

Стратегия исправления: НЕ патчим отдельные строки на месте (детект
"старая/новая форма" по самим данным ненадёжен — Sheets API обрезает
завершающие пустые ячейки строки непредсказуемо, например у почти
всегда пустого comment). Вместо этого полностью перегенерируем
затронутые листы из БД — единственного источника правды — тем же уже
протестированным кодом синка (workout_to_rows и т.д.), каким они
писались бы при первом запуске воркера на проекте с накопленной
историей. Из БД ничего не теряется, Sheets — только зеркало.

Использование (внутри контейнера app, где уже настроены переменные
окружения и volume с ключом сервисного аккаунта):

    python backfill_sheets_username.py --dry-run   # только отчёт, ничего не трогает (по умолчанию)
    python backfill_sheets_username.py --apply      # реальная перезапись листов + сброс курсоров

--dry-run:
    - показывает, сколько строк сейчас в каждом затронутом листе и сколько
      будет после перегенерации (в норме числа совпадают — строки не
      терялись, только сдвигались по смыслу);
    - показывает первые несколько СЫРЫХ строк листа как есть и то, что
      создаст для того же места регенерация — наглядно видно сдвиг.

--apply:
    - сбрасывает курсоры sheets_sync_state (last_event_id, last_workout_id,
      last_elective_id, last_subscription_id, last_coin_id,
      last_achievement_id) в 0;
    - очищает строки данных (не трогая заголовок) в events/workouts/
      subscriptions/coins/achievements;
    - запускает SheetsExportService.sync() — его же внутренняя пагинация
      сама пройдёт весь накопленный бэклог за один вызов, тем же кодом,
      что и обычный цикл синка.

equipment_items и users НЕ затронуты этим багом — оба листа полностью
перезаписываются (replace_all_rows) на КАЖДОМ цикле синка, поэтому уже
содержат актуальную структуру с первого же синка после деплоя username."""

import argparse
import asyncio

import gspread

from app.config import settings
from app.db.base import async_session_factory
from app.db.repositories.achievements import AchievementRepository
from app.db.repositories.coins import CoinRepository
from app.db.repositories.elective_workouts import ElectiveWorkoutRepository
from app.db.repositories.events import EventRepository
from app.db.repositories.sheets_sync_state import SheetsSyncStateRepository
from app.db.repositories.subscriptions import SubscriptionRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workouts import WorkoutRepository
from app.services.sheets_export import (
    ACHIEVEMENTS_HEADER,
    ACHIEVEMENTS_SHEET_TITLE,
    COINS_HEADER,
    COINS_SHEET_TITLE,
    EVENTS_HEADER,
    EVENTS_SHEET_TITLE,
    SUBSCRIPTIONS_HEADER,
    SUBSCRIPTIONS_SHEET_TITLE,
    WORKOUTS_HEADER,
    WORKOUTS_SHEET_TITLE,
    GspreadSheetsClient,
    SheetsExportService,
    achievement_to_row,
    coin_to_row,
    event_to_row,
    subscription_to_row,
    workout_to_rows,
)

_SAMPLE_SIZE = 3
_LIST_ALL_PAGE_SIZE = 10000


def _open_spreadsheet() -> gspread.Spreadsheet:
    client = gspread.service_account(filename=settings.google_sheets_credentials_path)
    return client.open_by_key(settings.google_sheets_spreadsheet_id)


async def _lookups(session):
    users = await UserRepository(session).list_all()
    telegram_id_by_id = {u.id: u.telegram_id for u in users}
    username_by_id = {u.id: u.username for u in users}
    return telegram_id_by_id, username_by_id


async def _report(session) -> None:
    spreadsheet = _open_spreadsheet()
    telegram_id_by_id, username_by_id = await _lookups(session)

    def tg(item):
        return telegram_id_by_id.get(item.user_id)

    def un(item):
        return username_by_id.get(item.user_id)

    events = await EventRepository(session).list_since(0, limit=_LIST_ALL_PAGE_SIZE)
    workouts = await WorkoutRepository(session).list_since(0, limit=_LIST_ALL_PAGE_SIZE)
    electives = await ElectiveWorkoutRepository(session).list_since(0, limit=_LIST_ALL_PAGE_SIZE)
    subscriptions = await SubscriptionRepository(session).list_since(0, limit=_LIST_ALL_PAGE_SIZE)
    coins = await CoinRepository(session).list_since(0, limit=_LIST_ALL_PAGE_SIZE)
    achievements = await AchievementRepository(session).list_since(0, limit=_LIST_ALL_PAGE_SIZE)

    expected_workout_rows = sum(len(workout_to_rows(w, telegram_id=tg(w), username=un(w))) for w in workouts)
    expected_workout_rows += len(electives)

    print("=" * 88)
    print("ОТЧЁТ (--dry-run, ничего не изменено)")
    print("=" * 88)

    _report_sheet_counts(spreadsheet, EVENTS_SHEET_TITLE, len(events))
    _report_sheet_counts(spreadsheet, WORKOUTS_SHEET_TITLE, expected_workout_rows)
    _report_sheet_counts(spreadsheet, SUBSCRIPTIONS_SHEET_TITLE, len(subscriptions))
    _report_sheet_counts(spreadsheet, COINS_SHEET_TITLE, len(coins))
    _report_sheet_counts(spreadsheet, ACHIEVEMENTS_SHEET_TITLE, len(achievements))

    print("\n--- Примеры: СЕЙЧАС в листе vs ПОСЛЕ регенерации (первые записи по id) ---\n")

    _print_sample(EVENTS_SHEET_TITLE, EVENTS_HEADER, spreadsheet,
                  [event_to_row(e, telegram_id=tg(e), username=un(e)) for e in events[:_SAMPLE_SIZE]])

    regenerated_workout_rows: list[list[str]] = []
    for w in workouts[:_SAMPLE_SIZE]:
        regenerated_workout_rows.extend(workout_to_rows(w, telegram_id=tg(w), username=un(w)))
    _print_sample(WORKOUTS_SHEET_TITLE, WORKOUTS_HEADER, spreadsheet, regenerated_workout_rows)

    _print_sample(SUBSCRIPTIONS_SHEET_TITLE, SUBSCRIPTIONS_HEADER, spreadsheet,
                  [subscription_to_row(s, telegram_id=tg(s), username=un(s)) for s in subscriptions[:_SAMPLE_SIZE]])
    _print_sample(COINS_SHEET_TITLE, COINS_HEADER, spreadsheet,
                  [coin_to_row(c, telegram_id=tg(c), username=un(c)) for c in coins[:_SAMPLE_SIZE]])
    _print_sample(ACHIEVEMENTS_SHEET_TITLE, ACHIEVEMENTS_HEADER, spreadsheet,
                  [achievement_to_row(a, telegram_id=tg(a), username=un(a)) for a in achievements[:_SAMPLE_SIZE]])

    print("\nequipment_items/users не затронуты — оба листа полностью")
    print("перезаписываются (replace_all_rows) на каждом цикле, уже актуальны.")


def _report_sheet_counts(spreadsheet: gspread.Spreadsheet, title: str, expected_rows: int) -> None:
    worksheet = spreadsheet.worksheet(title)
    current_rows = max(len(worksheet.get_all_values()) - 1, 0)
    match = "совпадает — строки не потеряны, только сдвинуты по смыслу" if current_rows == expected_rows else "!!! РАСХОДИТСЯ, разберись перед --apply"
    print(f"{title:>16}: сейчас в листе {current_rows:>5} строк, после регенерации будет {expected_rows:>5}  ({match})")


def _print_sample(title: str, header: list[str], spreadsheet: gspread.Spreadsheet, regenerated_rows: list[list[str]]) -> None:
    worksheet = spreadsheet.worksheet(title)
    current_rows = worksheet.get_all_values()[1:1 + len(regenerated_rows)]
    print(f"### {title} (заголовок: {header})")
    for i, regenerated in enumerate(regenerated_rows):
        current = current_rows[i] if i < len(current_rows) else None
        print(f"  БЫЛО ({title}, строка {i + 1}): {current}")
        print(f"  СТАНЕТ:                      {regenerated}")
    print()


async def _apply(session) -> None:
    print("=" * 88)
    print("ПРИМЕНЕНИЕ (--apply) — перезаписываю затронутые листы и сбрасываю курсоры")
    print("=" * 88)

    cursor = SheetsSyncStateRepository(session)
    for setter in (
        cursor.set_last_event_id, cursor.set_last_workout_id, cursor.set_last_elective_id,
        cursor.set_last_subscription_id, cursor.set_last_coin_id, cursor.set_last_achievement_id,
    ):
        await setter(0)
    await session.commit()
    print("Курсоры сброшены в 0.")

    spreadsheet = _open_spreadsheet()
    for title in (
        EVENTS_SHEET_TITLE, WORKOUTS_SHEET_TITLE, SUBSCRIPTIONS_SHEET_TITLE,
        COINS_SHEET_TITLE, ACHIEVEMENTS_SHEET_TITLE,
    ):
        worksheet = spreadsheet.worksheet(title)
        worksheet.batch_clear(["A2:Z100000"])
        print(f"Очистил строки данных в {title} (заголовок не тронут).")

    client = GspreadSheetsClient(
        credentials_path=settings.google_sheets_credentials_path,
        spreadsheet_id=settings.google_sheets_spreadsheet_id,
    )
    service = SheetsExportService(session, client)
    result = await service.sync()
    print(
        "Регенерация завершена: "
        f"events={result.events} workouts={result.workouts} electives={result.electives} "
        f"subscriptions={result.subscriptions} coins={result.coins} achievements={result.achievements}",
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="реально перезаписать листы (по умолчанию — только отчёт)")
    args = parser.parse_args()

    if not settings.google_sheets_spreadsheet_id or not settings.google_sheets_credentials_path:
        raise SystemExit("GOOGLE_SHEETS_SPREADSHEET_ID/GOOGLE_SHEETS_CREDENTIALS_PATH не настроены — нечего чинить.")

    async with async_session_factory() as session:
        if args.apply:
            await _apply(session)
        else:
            await _report(session)


if __name__ == "__main__":
    asyncio.run(main())
