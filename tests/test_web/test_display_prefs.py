"""GET/PUT /api/profile/prefs (issue #268) — единицы и тема, хранение остаётся метрическим."""

from dataclasses import dataclass
from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from app.db.models import User
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


async def _call(session, telegram_id: int, method: str, path: str, json: dict | None = None):
    app.dependency_overrides[get_validated_init_data] = (
        lambda: _FakeInitData(user=_FakeWebAppUser(id=telegram_id, first_name="Тест"))
    )

    async def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, json=json)
    finally:
        app.dependency_overrides.clear()


async def test_defaults_when_unset(session, user: User):
    response = await _call(session, user.telegram_id, "GET", "/api/profile/prefs")
    assert response.status_code == 200
    assert response.json() == {"weight_unit": "kg", "height_unit": "cm", "theme": "auto"}


async def test_put_persists_and_partial_update_keeps_other_fields(session, user: User):
    first = await _call(
        session, user.telegram_id, "PUT", "/api/profile/prefs",
        {"weight_unit": "lb", "height_unit": "in", "theme": "dark"},
    )
    assert first.json() == {"weight_unit": "lb", "height_unit": "in", "theme": "dark"}

    second = await _call(session, user.telegram_id, "PUT", "/api/profile/prefs", {"theme": "light"})
    assert second.json() == {"weight_unit": "lb", "height_unit": "in", "theme": "light"}

    again = await _call(session, user.telegram_id, "GET", "/api/profile/prefs")
    assert again.json() == {"weight_unit": "lb", "height_unit": "in", "theme": "light"}


async def test_put_rejects_unknown_values(session, user: User):
    for body in ({"weight_unit": "stone"}, {"height_unit": "ft"}, {"theme": "neon"}):
        response = await _call(session, user.telegram_id, "PUT", "/api/profile/prefs", body)
        assert response.status_code == 422, body


async def test_units_do_not_change_stored_metric_values(session, user: User):
    user.weight_kg = Decimal("80.5")
    user.height_cm = 180
    await session.flush()
    await _call(session, user.telegram_id, "PUT", "/api/profile/prefs", {"weight_unit": "lb", "height_unit": "in"})
    profile = (await _call(session, user.telegram_id, "GET", "/api/profile")).json()
    assert Decimal(str(profile["weight_kg"])) == Decimal("80.5")
    assert profile["height_cm"] == 180


async def test_unknown_user_gets_404(session):
    assert (await _call(session, 99999, "GET", "/api/profile/prefs")).status_code == 404
    assert (await _call(session, 99999, "PUT", "/api/profile/prefs", {"theme": "dark"})).status_code == 404
