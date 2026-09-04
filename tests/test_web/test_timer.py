"""POST /api/timer/start, GET /api/timer/status, DELETE /api/timer (issue
#59, волна 1) — персистентный таймер: время окончания на сервере, не в
localStorage клиента (см. app/db/models.py::ActiveTimer)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from httpx import ASGITransport, AsyncClient

from app.db.models import ActiveTimerType, User
from app.db.repositories.active_timers import ActiveTimerRepository
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.main import app


@dataclass
class _FakeWebAppUser:
    id: int
    first_name: str


@dataclass
class _FakeInitData:
    user: _FakeWebAppUser


def _override_dependencies(session, telegram_id: int) -> None:
    app.dependency_overrides[get_validated_init_data] = (
        lambda: _FakeInitData(user=_FakeWebAppUser(id=telegram_id, first_name="Тест"))
    )

    async def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session


async def _request(
    session, telegram_id: int, method: str, path: str, json: dict | None = None,
) -> dict:
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.request(method, path, json=json)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    return response.json()


async def test_start_timer_for_unknown_telegram_id_returns_404(session):
    _override_dependencies(session, telegram_id=61001)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/timer/start",
                json={"timer_type": "rest_between_sets", "duration_seconds": 90},
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404


async def test_start_timer_rejects_invalid_timer_type(session, user: User):
    _override_dependencies(session, telegram_id=user.telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/timer/start", json={"timer_type": "not_a_real_type", "duration_seconds": 90},
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 400


async def test_start_timer_rejects_duration_over_limit(session, user: User):
    _override_dependencies(session, telegram_id=user.telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/timer/start", json={"timer_type": "big_break", "duration_seconds": 3601},
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422


async def test_start_timer_returns_full_duration_as_remaining(session, user: User):
    body = await _request(
        session, user.telegram_id, "POST", "/api/timer/start",
        json={
            "timer_type": "rest_between_sets", "duration_seconds": 90,
            "block_letter": "A", "set_number": 2,
        },
    )

    assert body["active"] is True
    assert body["timer_type"] == "rest_between_sets"
    assert body["duration_seconds"] == 90
    assert body["remaining_seconds"] == 90
    assert body["block_letter"] == "A"
    assert body["set_number"] == 2


async def test_status_for_unknown_telegram_id_is_inactive(session):
    body = await _request(session, 61002, "GET", "/api/timer/status")
    assert body == {
        "active": False, "timer_type": None, "duration_seconds": None,
        "remaining_seconds": None, "block_letter": None, "set_number": None,
    }


async def test_status_without_active_timer_is_inactive(session, user: User):
    body = await _request(session, user.telegram_id, "GET", "/api/timer/status")
    assert body["active"] is False


async def test_status_reports_remaining_seconds_for_running_timer(session, user: User):
    started_at = datetime.now(UTC) - timedelta(seconds=30)
    await ActiveTimerRepository(session).start(
        user_id=user.id, timer_type=ActiveTimerType.BIG_BREAK,
        started_at=started_at, duration_seconds=180,
    )

    body = await _request(session, user.telegram_id, "GET", "/api/timer/status")

    assert body["active"] is True
    assert body["timer_type"] == "big_break"
    # 30 секунд уже прошло из 180 — допускаем небольшой дрейф между
    # фиксацией started_at выше и моментом запроса ниже.
    assert 145 <= body["remaining_seconds"] <= 150


async def test_status_reports_expired_timer_as_inactive_but_keeps_context(session, user: User):
    started_at = datetime.now(UTC) - timedelta(seconds=200)
    await ActiveTimerRepository(session).start(
        user_id=user.id, timer_type=ActiveTimerType.REST_BETWEEN_SETS, started_at=started_at,
        duration_seconds=90, block_letter="B", set_number=3,
    )

    body = await _request(session, user.telegram_id, "GET", "/api/timer/status")

    assert body["active"] is False
    assert body["remaining_seconds"] == 0
    # Контекст (тип/блок/подход) остаётся даже у истёкшего таймера — не
    # удаляется при чтении (см. app/web/routes.py::_timer_status_response).
    assert body["timer_type"] == "rest_between_sets"
    assert body["block_letter"] == "B"
    assert body["set_number"] == 3


async def test_start_replaces_previously_running_timer(session, user: User):
    await _request(
        session, user.telegram_id, "POST", "/api/timer/start",
        json={"timer_type": "rest_between_sets", "duration_seconds": 60},
    )

    body = await _request(
        session, user.telegram_id, "POST", "/api/timer/start",
        json={"timer_type": "big_break", "duration_seconds": 300},
    )

    assert body["timer_type"] == "big_break"
    assert body["remaining_seconds"] == 300

    status_body = await _request(session, user.telegram_id, "GET", "/api/timer/status")
    assert status_body["timer_type"] == "big_break"


async def test_cancel_timer_removes_active_timer(session, user: User):
    await _request(
        session, user.telegram_id, "POST", "/api/timer/start",
        json={"timer_type": "rest_between_sets", "duration_seconds": 60},
    )

    cancel_body = await _request(session, user.telegram_id, "DELETE", "/api/timer")
    assert cancel_body["active"] is False

    status_body = await _request(session, user.telegram_id, "GET", "/api/timer/status")
    assert status_body["active"] is False
    assert status_body["timer_type"] is None


async def test_cancel_timer_is_idempotent_without_active_timer(session, user: User):
    body = await _request(session, user.telegram_id, "DELETE", "/api/timer")
    assert body["active"] is False


async def test_cancel_timer_for_unknown_telegram_id_is_ok(session):
    body = await _request(session, 61003, "DELETE", "/api/timer")
    assert body["active"] is False


# --- GET/PUT /api/timer/preferences (issue #59, волна 2) --------------------------------


async def test_get_preferences_returns_defaults_when_unset(session, user: User):
    body = await _request(session, user.telegram_id, "GET", "/api/timer/preferences")
    assert body == {
        "rest_seconds_block_a": 240, "rest_seconds_block_b": 180, "big_break_seconds": 900,
    }


async def test_get_preferences_for_unknown_telegram_id_returns_404(session):
    _override_dependencies(session, telegram_id=61004)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/timer/preferences")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404


async def test_put_preferences_updates_block_a_only(session, user: User):
    body = await _request(
        session, user.telegram_id, "PUT", "/api/timer/preferences",
        json={"block_letter": "A", "duration_seconds": 300},
    )
    assert body == {
        "rest_seconds_block_a": 300, "rest_seconds_block_b": 180, "big_break_seconds": 900,
    }


async def test_put_preferences_updates_block_b_only(session, user: User):
    body = await _request(
        session, user.telegram_id, "PUT", "/api/timer/preferences",
        json={"block_letter": "B", "duration_seconds": 150},
    )
    assert body == {
        "rest_seconds_block_a": 240, "rest_seconds_block_b": 150, "big_break_seconds": 900,
    }


async def test_put_preferences_updates_big_break_when_block_letter_omitted(session, user: User):
    body = await _request(
        session, user.telegram_id, "PUT", "/api/timer/preferences",
        json={"duration_seconds": 600},
    )
    assert body == {
        "rest_seconds_block_a": 240, "rest_seconds_block_b": 180, "big_break_seconds": 600,
    }


async def test_put_preferences_persists_across_requests(session, user: User):
    await _request(
        session, user.telegram_id, "PUT", "/api/timer/preferences",
        json={"block_letter": "A", "duration_seconds": 300},
    )

    body = await _request(session, user.telegram_id, "GET", "/api/timer/preferences")

    assert body["rest_seconds_block_a"] == 300


async def test_put_preferences_rejects_duration_over_limit(session, user: User):
    _override_dependencies(session, telegram_id=user.telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                "/api/timer/preferences", json={"block_letter": "A", "duration_seconds": 3601},
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 422
