"""Выгрузка в Google Sheets (ROADMAP Часть 6 «Аналитика») — против
SheetsClientProtocol через фейковую реализацию, без обращения к реальному
Google API (та же схема, что и TributeService/TributeClientProtocol)."""

from datetime import UTC, datetime

import requests
from gspread.exceptions import APIError

from app.db.models import User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.events import EventRepository
from app.db.repositories.users import UserRepository
from app.services.sheets_export import (
    EVENTS_HEADER,
    EVENTS_SHEET_TITLE,
    USERS_HEADER,
    USERS_SHEET_TITLE,
    SheetsExportService,
    _call_with_retry,
    _chunk,
    event_to_row,
    user_to_row,
)


class FakeSheetsClient:
    def __init__(self) -> None:
        self.appended: list[tuple[str, list[str], list[list[str]]]] = []
        self.replaced: list[tuple[str, list[str], list[list[str]]]] = []

    async def append_rows(self, sheet_title, header, rows):
        self.appended.append((sheet_title, header, rows))

    async def replace_all_rows(self, sheet_title, header, rows):
        self.replaced.append((sheet_title, header, rows))


def _fake_api_error(status_code: int) -> APIError:
    response = requests.Response()
    response.status_code = status_code
    response._content = (
        b'{"error": {"code": %d, "message": "boom", "status": "ERR"}}' % status_code
    )
    return APIError(response)


# --- Форматирование строк -----------------------------------------------------------


async def test_event_to_row_includes_telegram_id_and_flat_payload(session, user: User):
    event = await EventRepository(session).create(
        user_id=user.id, event_type="workout_completed", payload={"workout_id": 5},
    )
    row = event_to_row(event, telegram_id=user.telegram_id)
    assert row[0] == str(event.id)
    assert row[1] == str(user.id)
    assert row[2] == str(user.telegram_id)
    assert row[3] == "workout_completed"
    assert "workout_id=5" in row[4]


async def test_event_to_row_handles_missing_telegram_id(session, user: User):
    event = await EventRepository(session).create(user_id=user.id, event_type="x")
    row = event_to_row(event, telegram_id=None)
    assert row[2] == ""


async def test_event_to_row_empty_payload_is_empty_string(session, user: User):
    event = await EventRepository(session).create(user_id=user.id, event_type="x")
    row = event_to_row(event, telegram_id=1)
    assert row[4] == ""


async def test_user_to_row_handles_all_none_optional_fields(session, user: User):
    row = user_to_row(user)
    assert row[0] == str(user.id)
    assert row[1] == str(user.telegram_id)
    assert row[3] == ""  # onboarding_completed_at
    assert row[5] == ""  # subscription_expires_at


async def test_user_to_row_fills_onboarded_fields(session, user: User):
    await UserRepository(session).complete_onboarding(user.id, datetime.now(UTC))
    await session.refresh(user)
    row = user_to_row(user)
    assert row[3] != ""


# --- Батчирование -----------------------------------------------------------------


def test_chunk_splits_into_groups_of_given_size():
    rows = [[str(i)] for i in range(7)]
    chunks = _chunk(rows, 3)
    assert [len(c) for c in chunks] == [3, 3, 1]


def test_chunk_of_empty_list_is_empty():
    assert _chunk([], 500) == []


def test_chunk_smaller_than_size_is_single_chunk():
    rows = [[str(i)] for i in range(3)]
    assert _chunk(rows, 500) == [rows]


# --- Retry на 429 -------------------------------------------------------------------


async def test_call_with_retry_succeeds_immediately_when_no_error():
    calls = []

    def ok():
        calls.append(1)
        return "done"

    await _call_with_retry(ok)
    assert calls == [1]


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


async def test_call_with_retry_gives_up_after_max_retries(monkeypatch):
    import app.services.sheets_export as module

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(module.asyncio, "sleep", _no_sleep)

    calls = {"n": 0}

    def always_429():
        calls["n"] += 1
        raise _fake_api_error(429)

    try:
        await _call_with_retry(always_429)
        raise AssertionError("expected APIError to propagate after exhausting retries")
    except APIError:
        pass
    assert calls["n"] == module._MAX_RETRIES


# --- SheetsExportService.sync() ------------------------------------------------------


async def test_sync_with_no_events_still_writes_users_snapshot(session, user: User):
    client = FakeSheetsClient()
    service = SheetsExportService(session, client)

    events_synced, users_count = await service.sync()

    assert events_synced == 0
    assert users_count == 1
    assert client.appended == []
    [(title, header, rows)] = client.replaced
    assert title == USERS_SHEET_TITLE
    assert header == USERS_HEADER
    assert len(rows) == 1


async def test_sync_appends_only_new_events_and_advances_cursor(session, user: User):
    events = EventRepository(session)
    await events.create(user_id=user.id, event_type="a")
    await events.create(user_id=user.id, event_type="b")

    client = FakeSheetsClient()
    service = SheetsExportService(session, client)
    events_synced, _ = await service.sync()

    assert events_synced == 2
    [(title, header, rows)] = client.appended
    assert title == EVENTS_SHEET_TITLE
    assert header == EVENTS_HEADER
    assert len(rows) == 2

    # Второй прогон без новых событий — ничего заново не выгружает.
    client.appended.clear()
    events_synced_again, _ = await service.sync()
    assert events_synced_again == 0
    assert client.appended == []


async def test_sync_picks_up_only_events_added_since_last_sync(session, user: User):
    events = EventRepository(session)
    await events.create(user_id=user.id, event_type="first")

    client = FakeSheetsClient()
    service = SheetsExportService(session, client)
    await service.sync()

    await events.create(user_id=user.id, event_type="second")
    client.appended.clear()
    events_synced, _ = await service.sync()

    assert events_synced == 1
    [(_, _, rows)] = client.appended
    assert rows[0][3] == "second"


async def test_sync_paginates_large_backlog_across_multiple_pages(session, user: User):
    events = EventRepository(session)
    for i in range(5):
        await events.create(user_id=user.id, event_type=f"event_{i}")

    client = FakeSheetsClient()
    service = SheetsExportService(session, client)
    events_synced, _ = await service.sync(events_page_size=2)

    assert events_synced == 5
    # 5 событий по 2 на страницу -> 3 отдельных вызова append_rows
    assert len(client.appended) == 3
    assert [len(rows) for (_, _, rows) in client.appended] == [2, 2, 1]


async def test_sync_users_snapshot_includes_everyone_regardless_of_baseline(session, user: User):
    await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    another = await UserRepository(session).create(telegram_id=2002, username="second")

    client = FakeSheetsClient()
    service = SheetsExportService(session, client)
    _, users_count = await service.sync()

    assert users_count == 2
    [(_, _, rows)] = client.replaced
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

    [(_, _, rows)] = client.appended
    by_type = {row[3]: row[2] for row in rows}
    assert by_type["a"] == str(user.telegram_id)
    assert by_type["b"] == str(other.telegram_id)
