"""Выгрузка в Google Sheets (ROADMAP Часть 6, ревизия — пакет #7) — против
SheetsClientProtocol через фейковую реализацию, без обращения к реальному
Google API (та же схема, что и TributeService/TributeClientProtocol)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import requests
from gspread.exceptions import APIError

from app.db.models import CoinReason, SubscriptionSource, SubscriptionStatus, User
from app.db.repositories.achievements import AchievementRepository
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.coins import CoinRepository
from app.db.repositories.elective_workouts import ElectiveWorkoutRepository
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.events import EventRepository
from app.db.repositories.subscriptions import SubscriptionRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.electives import ElectiveType
from app.domain.session import BlockLog
from app.services.sheets_export import (
    ACHIEVEMENTS_SHEET_TITLE,
    ALL_SHEET_TITLES,
    COINS_SHEET_TITLE,
    EQUIPMENT_ITEMS_HEADER,
    EQUIPMENT_ITEMS_SHEET_TITLE,
    EVENTS_HEADER,
    EVENTS_SHEET_TITLE,
    SUBSCRIPTIONS_SHEET_TITLE,
    USERS_HEADER,
    USERS_SHEET_TITLE,
    WORKOUTS_SHEET_TITLE,
    SheetsExportService,
    _basic_filter_request,
    _bold_header_request,
    _call_with_retry,
    _chunk,
    _freeze_header_request,
    achievement_to_row,
    coin_to_row,
    elective_to_row,
    equipment_item_to_row,
    event_to_row,
    subscription_to_row,
    user_to_row,
    workout_to_rows,
)


class FakeSheetsClient:
    def __init__(self) -> None:
        self.appended: list[tuple[str, list[str], list[list[str]]]] = []
        self.replaced: list[tuple[str, list[str], list[list[str]]]] = []
        self.formatted_sheet_titles: list[list[str]] = []

    async def append_rows(self, sheet_title, header, rows):
        self.appended.append((sheet_title, header, rows))

    async def replace_all_rows(self, sheet_title, header, rows):
        self.replaced.append((sheet_title, header, rows))

    async def ensure_sheet_formatting(self, sheet_titles):
        self.formatted_sheet_titles.append(list(sheet_titles))


def _fake_api_error(status_code: int) -> APIError:
    response = requests.Response()
    response.status_code = status_code
    response._content = (
        b'{"error": {"code": %d, "message": "boom", "status": "ERR"}}' % status_code
    )
    return APIError(response)


async def _make_workout_set(session, user: User) -> int:
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    return workout_set.id


# --- Форматирование строк: events/users -----------------------------------------------


async def test_event_to_row_includes_telegram_id_and_flat_payload(session, user: User):
    event = await EventRepository(session).create(
        user_id=user.id, event_type="workout_completed", payload={"workout_id": 5},
    )
    row = event_to_row(event, telegram_id=user.telegram_id, username=user.username)
    assert row[0] == str(event.id)
    assert row[1] == str(user.id)
    assert row[2] == str(user.telegram_id)
    assert row[3] == user.username
    assert row[4] == "workout_completed"
    assert "workout_id=5" in row[5]


async def test_event_to_row_handles_missing_telegram_id(session, user: User):
    event = await EventRepository(session).create(user_id=user.id, event_type="x")
    row = event_to_row(event, telegram_id=None, username=None)
    assert row[2] == ""
    assert row[3] == ""


async def test_user_to_row_handles_all_none_optional_fields(session, user: User):
    row = user_to_row(user)
    assert row[0] == str(user.id)
    assert row[1] == str(user.telegram_id)
    assert row[3] == ""  # onboarding_completed_at
    assert row[6] == ""  # subscription_expires_at


async def test_user_to_row_fills_onboarded_fields(session, user: User):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await session.refresh(user)
    row = user_to_row(user)
    assert row[3] != ""


async def test_user_to_row_onboarding_stage_not_started(session, user: User):
    row = user_to_row(user)
    assert row[4] == "анкета не начата"


async def test_user_to_row_onboarding_stage_in_progress(session, user: User):
    await UserRepository(session).update_profile(user.id, weight_kg=Decimal("70.0"), height_cm=175)
    await session.refresh(user)
    row = user_to_row(user)
    assert row[4] == "анкета в процессе (2/5)"


async def test_user_to_row_onboarding_stage_completed_no_subscription(session, user: User):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await session.refresh(user)
    row = user_to_row(user)
    assert row[4] == "анкета завершена, без подписки"


async def test_user_to_row_onboarding_stage_completed_with_subscription(session, user: User):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await UserRepository(session).update_subscription_cache(
        user.id, status=SubscriptionStatus.TRIAL, expires_at=datetime.now(UTC) + timedelta(days=14),
    )
    await session.refresh(user)
    row = user_to_row(user)
    assert row[4] == "анкета завершена, подписка: trial"


# --- Форматирование строк: workouts/electives ------------------------------------------


async def test_workout_to_rows_live_produces_two_rows(session, user: User):
    workout_set_id = await _make_workout_set(session, user)
    workout = await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=datetime(2026, 1, 5, tzinfo=UTC),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=Decimal("20.0"),
    )

    rows = workout_to_rows(workout, telegram_id=user.telegram_id, username=user.username)

    assert len(rows) == 2
    row_a, row_b = rows
    assert row_a[1] == "live"
    assert row_a[4] == user.username
    assert row_a[6] == "a"
    assert row_a[7] == "bodyweight"
    assert row_a[9] == "11, 11, 11"
    assert row_a[10] == "12"
    assert row_b[6] == "b"
    assert row_b[7] == "weight"
    assert row_b[8] == "20.00"


async def test_workout_to_rows_free_entry_skips_dummy_block_b(session, user: User):
    workout_set_id = await _make_workout_set(session, user)
    workout = await WorkoutRepository(session).record_free_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=datetime.now(UTC),
        block_a_reps=BlockLog(working_reps=(8, 6, 4), max_reps=4), equipment_type=EquipmentType.BODYWEIGHT,
    )

    rows = workout_to_rows(workout, telegram_id=user.telegram_id, username=user.username)

    assert len(rows) == 1
    assert rows[0][1] == "free"
    assert rows[0][6] == "a"


async def test_workout_to_rows_backdated_entry_type(session, user: User):
    workout_set_id = await _make_workout_set(session, user)
    workout = await WorkoutRepository(session).record_backdated_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=datetime.now(UTC),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )

    rows = workout_to_rows(workout, telegram_id=user.telegram_id, username=user.username)
    assert {row[1] for row in rows} == {"backdated"}


async def test_elective_to_row_with_sequence(session, user: User):
    elective = await ElectiveWorkoutRepository(session).create(
        user_id=user.id, elective_type=ElectiveType.MAX_REPS_LADDER, performed_at=datetime.now(UTC),
        total_reps=36, reps_sequence=[12, 10, 8, 6], equipment_type=EquipmentType.BODYWEIGHT,
    )

    row = elective_to_row(elective, telegram_id=user.telegram_id, username=user.username)

    assert row[1] == "elective_max_reps_ladder"
    assert row[4] == user.username
    assert row[6] == "-"
    assert row[9] == "12, 10, 8, 6"
    assert row[10] == ""  # max_reps не применимо
    assert row[11] == ""  # target_before не применимо
    assert row[13] == "36"  # volume = total_reps


async def test_elective_to_row_without_sequence(session, user: User):
    elective = await ElectiveWorkoutRepository(session).create(
        user_id=user.id, elective_type=ElectiveType.VOLUME_TARGET, performed_at=datetime.now(UTC),
        total_reps=52, reps_sequence=None, equipment_type=EquipmentType.BAND,
    )

    row = elective_to_row(elective, telegram_id=user.telegram_id, username=user.username)
    assert row[9] == ""
    assert row[13] == "52"


# --- Форматирование строк: subscriptions/coins/achievements/equipment_items -----------


async def test_subscription_to_row(session, user: User):
    subscription = await SubscriptionRepository(session).create(
        user_id=user.id, status=SubscriptionStatus.TRIAL, source=SubscriptionSource.TRIAL,
        started_at=datetime(2026, 1, 1, tzinfo=UTC), ends_at=datetime(2026, 1, 15, tzinfo=UTC),
    )
    row = subscription_to_row(subscription, telegram_id=user.telegram_id, username=user.username)
    assert row[3] == user.username
    assert row[4] == "trial"
    assert row[5] == "trial"
    assert row[8] == ""  # payment_reference


async def test_coin_to_row(session, user: User):
    coin = await CoinRepository(session).create_transaction(
        user_id=user.id, amount=5, reason=CoinReason.WORKOUT_COMPLETED,
    )
    row = coin_to_row(coin, telegram_id=user.telegram_id, username=user.username)
    assert row[3] == user.username
    assert row[4] == "5"
    assert row[5] == "workout_completed"
    assert row[6] == ""  # related_achievement_id


async def test_achievement_to_row(session, user: User):
    achievement = await AchievementRepository(session).unlock(
        user_id=user.id, code="first_baseline", context={"value": 10},
    )
    row = achievement_to_row(achievement, telegram_id=user.telegram_id, username=user.username)
    assert row[3] == user.username
    assert row[4] == "first_baseline"
    assert "value=10" in row[6]


async def test_equipment_item_to_row(session, user: User):
    item = await EquipmentItemRepository(session).create(
        user_id=user.id, name="зелёная", resistance_kg=Decimal("25.0"),
    )
    row = equipment_item_to_row(item, telegram_id=user.telegram_id, username=user.username)
    assert row[3] == user.username
    assert row[4] == "зелёная"
    assert row[5] == "25.0"
    assert row[6] == "0"


# --- Батчирование / retry (без изменений в логике) -------------------------------------


def test_chunk_splits_into_groups_of_given_size():
    rows = [[str(i)] for i in range(7)]
    chunks = _chunk(rows, 3)
    assert [len(c) for c in chunks] == [3, 3, 1]


async def test_call_with_retry_retries_on_429_then_succeeds(monkeypatch):
    import app.services.sheets_export as module

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(module.asyncio, "sleep", _no_sleep)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _fake_api_error(429)
        return "ok"

    await _call_with_retry(flaky)
    assert calls["n"] == 3


async def test_call_with_retry_does_not_retry_non_429_errors():
    def always_fails():
        raise _fake_api_error(403)

    try:
        await _call_with_retry(always_fails)
        raise AssertionError("expected APIError to propagate")
    except APIError as error:
        assert error.code == 403


# --- SheetsExportService.sync() ---------------------------------------------------------


async def test_sync_with_nothing_at_all_still_writes_empty_snapshots(session, user: User):
    client = FakeSheetsClient()
    service = SheetsExportService(session, client)

    result = await service.sync()

    assert (result.events, result.workouts, result.electives) == (0, 0, 0)
    assert (result.subscriptions, result.coins, result.achievements) == (0, 0, 0)
    assert result.users == 1
    assert result.equipment_items == 0
    assert client.appended == []
    titles = {title for title, _, _ in client.replaced}
    assert titles == {USERS_SHEET_TITLE, EQUIPMENT_ITEMS_SHEET_TITLE}


async def test_sync_appends_only_new_events_and_advances_cursor(session, user: User):
    events = EventRepository(session)
    await events.create(user_id=user.id, event_type="a")
    await events.create(user_id=user.id, event_type="b")

    client = FakeSheetsClient()
    service = SheetsExportService(session, client)
    result = await service.sync()

    assert result.events == 2
    [(title, header, rows)] = [row for row in client.appended if row[0] == EVENTS_SHEET_TITLE]
    assert title == EVENTS_SHEET_TITLE
    assert header == EVENTS_HEADER
    assert len(rows) == 2

    client.appended.clear()
    result_again = await service.sync()
    assert result_again.events == 0
    assert client.appended == []


async def test_sync_paginates_large_backlog_across_multiple_pages(session, user: User):
    events = EventRepository(session)
    for i in range(5):
        await events.create(user_id=user.id, event_type=f"event_{i}")

    client = FakeSheetsClient()
    service = SheetsExportService(session, client)
    result = await service.sync(page_size=2)

    assert result.events == 5
    event_appends = [row for row in client.appended if row[0] == EVENTS_SHEET_TITLE]
    # 5 событий по 2 на страницу -> 3 отдельных вызова append_rows
    assert len(event_appends) == 3
    assert [len(rows) for (_, _, rows) in event_appends] == [2, 2, 1]


async def test_sync_workouts_and_electives_share_one_sheet_with_separate_cursors(session, user: User):
    workout_set_id = await _make_workout_set(session, user)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=datetime.now(UTC),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )
    await ElectiveWorkoutRepository(session).create(
        user_id=user.id, elective_type=ElectiveType.VOLUME_TARGET, performed_at=datetime.now(UTC),
        total_reps=52, reps_sequence=None, equipment_type=EquipmentType.BAND,
    )

    client = FakeSheetsClient()
    service = SheetsExportService(session, client)
    result = await service.sync()

    assert result.workouts == 1  # 1 запись-тренировка (даёт 2 строки)
    assert result.electives == 1
    workout_sheet_appends = [row for row in client.appended if row[0] == WORKOUTS_SHEET_TITLE]
    all_rows = [row for (_, _, rows) in workout_sheet_appends for row in rows]
    assert len(all_rows) == 3  # 2 строки от тренировки + 1 от факультатива
    assert {row[7] for row in [r for r in all_rows if r[1] == "live"]} == {"bodyweight"}
    assert any(row[1] == "elective_volume_target" for row in all_rows)

    # Второй прогон без новых записей — курсоры обоих источников
    # действительно продвинулись, не только один из двух.
    client.appended.clear()
    result_again = await service.sync()
    assert (result_again.workouts, result_again.electives) == (0, 0)
    assert client.appended == []


async def test_sync_subscriptions_coins_achievements_are_incremental(session, user: User):
    await SubscriptionRepository(session).create(
        user_id=user.id, status=SubscriptionStatus.TRIAL, source=SubscriptionSource.TRIAL,
        started_at=datetime.now(UTC), ends_at=datetime.now(UTC) + timedelta(days=14),
    )
    await CoinRepository(session).create_transaction(user_id=user.id, amount=5, reason=CoinReason.WORKOUT_COMPLETED)
    await AchievementRepository(session).unlock(user_id=user.id, code="first_baseline")

    client = FakeSheetsClient()
    service = SheetsExportService(session, client)
    result = await service.sync()

    assert (result.subscriptions, result.coins, result.achievements) == (1, 1, 1)
    titles = {title for title, _, _ in client.appended}
    assert titles == {SUBSCRIPTIONS_SHEET_TITLE, COINS_SHEET_TITLE, ACHIEVEMENTS_SHEET_TITLE}

    client.appended.clear()
    result_again = await service.sync()
    assert (result_again.subscriptions, result_again.coins, result_again.achievements) == (0, 0, 0)
    assert client.appended == []


async def test_sync_equipment_items_snapshot_replaces_not_appends(session, user: User):
    await EquipmentItemRepository(session).create(user_id=user.id, name="зелёная")

    client = FakeSheetsClient()
    service = SheetsExportService(session, client)
    result = await service.sync()

    assert result.equipment_items == 1
    [(_, header, rows)] = [row for row in client.replaced if row[0] == EQUIPMENT_ITEMS_SHEET_TITLE]
    assert header == EQUIPMENT_ITEMS_HEADER
    assert len(rows) == 1

    # Снапшот, не история — второй прогон без новых резин снова
    # перезаписывает тот же единственный ряд, не накапливает записи.
    client.replaced.clear()
    await service.sync()
    [(_, _, rows_again)] = [row for row in client.replaced if row[0] == EQUIPMENT_ITEMS_SHEET_TITLE]
    assert len(rows_again) == 1


async def test_sync_users_snapshot_includes_everyone_regardless_of_baseline(session, user: User):
    await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    another = await UserRepository(session).create(telegram_id=2002, username="second")

    client = FakeSheetsClient()
    service = SheetsExportService(session, client)
    result = await service.sync()

    assert result.users == 2
    [(_, header, rows)] = [row for row in client.replaced if row[0] == USERS_SHEET_TITLE]
    assert header == USERS_HEADER
    telegram_ids = {row[1] for row in rows}
    assert telegram_ids == {str(user.telegram_id), str(another.telegram_id)}


async def test_sync_events_include_correct_telegram_id_for_multiple_users(session, user: User):
    other = await UserRepository(session).create(telegram_id=2002, username="second")
    events = EventRepository(session)
    await events.create(user_id=user.id, event_type="a")
    await events.create(user_id=other.id, event_type="b")

    client = FakeSheetsClient()
    service = SheetsExportService(session, client)
    await service.sync()

    [(_, _, rows)] = [row for row in client.appended if row[0] == EVENTS_SHEET_TITLE]
    telegram_id_by_type = {row[4]: row[2] for row in rows}
    username_by_type = {row[4]: row[3] for row in rows}
    assert telegram_id_by_type["a"] == str(user.telegram_id)
    assert telegram_id_by_type["b"] == str(other.telegram_id)
    assert username_by_type["a"] == user.username
    assert username_by_type["b"] == "second"


async def test_sync_joins_username_into_workouts_subscriptions_coins_achievements(session, user: User):
    """Реальная жалоба, подтверждённая прямой сверкой данных: только
    telegram_id в этих 4 листах, приходилось вручную сопоставлять с users."""
    workout_set_id = await _make_workout_set(session, user)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set_id, performed_at=datetime.now(UTC),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )
    await SubscriptionRepository(session).create(
        user_id=user.id, status=SubscriptionStatus.TRIAL, source=SubscriptionSource.TRIAL,
        started_at=datetime.now(UTC), ends_at=datetime.now(UTC) + timedelta(days=14),
    )
    await CoinRepository(session).create_transaction(user_id=user.id, amount=5, reason=CoinReason.WORKOUT_COMPLETED)
    await AchievementRepository(session).unlock(user_id=user.id, code="first_baseline")

    client = FakeSheetsClient()
    service = SheetsExportService(session, client)
    await service.sync()

    workout_rows = [
        row for (title, _, rows) in client.appended if title == WORKOUTS_SHEET_TITLE
        for row in rows if row[1] == "live"
    ]
    assert workout_rows and all(row[4] == user.username for row in workout_rows)

    for title, username_index in (
        (SUBSCRIPTIONS_SHEET_TITLE, 3), (COINS_SHEET_TITLE, 3), (ACHIEVEMENTS_SHEET_TITLE, 3),
    ):
        [(_, _, rows)] = [row for row in client.appended if row[0] == title]
        assert all(row[username_index] == user.username for row in rows)


async def test_sync_joins_username_into_events_and_equipment_items(session, user: User):
    """Тем же способом, что и в остальных четырёх листах — тот же словарь
    user_id -> username, уже загруженный в sync(), без новых запросов к БД."""
    await EventRepository(session).create(user_id=user.id, event_type="workout_completed")
    await EquipmentItemRepository(session).create(user_id=user.id, name="зелёная")

    client = FakeSheetsClient()
    service = SheetsExportService(session, client)
    await service.sync()

    [(_, _, event_rows)] = [row for row in client.appended if row[0] == EVENTS_SHEET_TITLE]
    assert all(row[3] == user.username for row in event_rows)

    [(_, _, equipment_rows)] = [row for row in client.replaced if row[0] == EQUIPMENT_ITEMS_SHEET_TITLE]
    assert all(row[3] == user.username for row in equipment_rows)


# --- Форматирование листов: заморозка/фильтр/жирная шапка (пакет #7) ------------------


def test_freeze_header_request_shape():
    request = _freeze_header_request(42)
    props = request["updateSheetProperties"]
    assert props["properties"] == {"sheetId": 42, "gridProperties": {"frozenRowCount": 1}}
    assert props["fields"] == "gridProperties.frozenRowCount"


def test_basic_filter_request_covers_whole_sheet():
    request = _basic_filter_request(42)
    # Диапазон без явных границ строк/колонок = весь лист целиком.
    assert request["setBasicFilter"]["filter"]["range"] == {"sheetId": 42}


def test_bold_header_request_targets_only_first_row():
    request = _bold_header_request(42)
    cell = request["repeatCell"]
    assert cell["range"] == {"sheetId": 42, "startRowIndex": 0, "endRowIndex": 1}
    assert cell["cell"]["userEnteredFormat"]["textFormat"] == {"bold": True}
    assert "backgroundColor" in cell["cell"]["userEnteredFormat"]
    assert cell["fields"] == "userEnteredFormat(textFormat,backgroundColor)"


async def test_sync_calls_ensure_sheet_formatting_with_every_sheet_title(session, user: User):
    client = FakeSheetsClient()
    service = SheetsExportService(session, client)

    await service.sync()

    assert client.formatted_sheet_titles == [ALL_SHEET_TITLES]


async def test_sync_calls_ensure_sheet_formatting_every_cycle_even_with_nothing_new(
    session, user: User,
):
    """Идемпотентно и дёшево (см. GspreadSheetsClient.ensure_sheet_formatting
    — один batchUpdate) — само-восстанавливает форматирование уже
    существующих в проде листов, не только вновь создаваемых, поэтому
    вызывается каждый цикл безусловно, а не только при первом создании."""
    client = FakeSheetsClient()
    service = SheetsExportService(session, client)

    await service.sync()
    await service.sync()

    assert len(client.formatted_sheet_titles) == 2
