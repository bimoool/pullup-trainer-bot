"""/api/profile/body-metrics (issue #270) — история веса/роста, зеркало в User."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from app.db.models import User
from app.db.repositories.users import UserRepository
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.main import app

URL = "/api/profile/body-metrics"


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


def _days_ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


async def test_profile_write_appends_history_once_per_change(session, user: User):
    users = UserRepository(session)
    await users.update_profile(user.id, weight_kg=Decimal(80), height_cm=180)
    await users.update_profile(user.id, weight_kg=Decimal(80), height_cm=180)  # без изменений — без дубля
    await users.update_profile(user.id, weight_kg=Decimal("79.5"))

    weight = (await _call(session, user.telegram_id, "GET", f"{URL}?metric=weight_kg")).json()
    assert [Decimal(i["value"]) for i in weight["items"]] == [Decimal("79.5"), Decimal(80)]
    height = (await _call(session, user.telegram_id, "GET", f"{URL}?metric=height_cm")).json()
    assert len(height["items"]) == 1


async def test_add_mirrors_latest_but_backdated_entry_does_not(session, user: User):
    await UserRepository(session).update_profile(user.id, weight_kg=Decimal(80))

    response = await _call(
        session, user.telegram_id, "POST", URL, {"metric": "weight_kg", "value": "78.4", "measured_at": _days_ago(10)},
    )
    assert response.status_code == 201
    assert Decimal(response.json()["current"]) == Decimal("80.00")
    await session.refresh(user)
    assert user.weight_kg == Decimal("80.00")

    response = await _call(session, user.telegram_id, "POST", URL, {"metric": "weight_kg", "value": "77"})
    assert Decimal(response.json()["current"]) == Decimal("77.00")
    await session.refresh(user)
    assert user.weight_kg == Decimal("77.00")


async def test_edit_latest_updates_mirror_and_delete_latest_falls_back(session, user: User):
    users = UserRepository(session)
    await users.update_profile(user.id, weight_kg=Decimal(80))
    await _call(session, user.telegram_id, "POST", URL, {"metric": "weight_kg", "value": "79"})
    items = (await _call(session, user.telegram_id, "GET", f"{URL}?metric=weight_kg")).json()["items"]
    latest_id = items[0]["id"]

    response = await _call(session, user.telegram_id, "PATCH", f"{URL}/{latest_id}", {"value": "78.5"})
    assert response.status_code == 200
    await session.refresh(user)
    assert user.weight_kg == Decimal("78.50")

    response = await _call(session, user.telegram_id, "DELETE", f"{URL}/{latest_id}")
    assert response.status_code == 200
    assert [Decimal(i["value"]) for i in response.json()["items"]] == [Decimal(80)]
    await session.refresh(user)
    assert user.weight_kg == Decimal("80.00")


async def test_cannot_delete_only_entry(session, user: User):
    await UserRepository(session).update_profile(user.id, weight_kg=Decimal(80))
    only = (await _call(session, user.telegram_id, "GET", f"{URL}?metric=weight_kg")).json()["items"][0]["id"]

    response = await _call(session, user.telegram_id, "DELETE", f"{URL}/{only}")
    assert response.status_code == 409
    await session.refresh(user)
    assert user.weight_kg == Decimal("80.00")


async def test_foreign_entry_is_404(session, user: User):
    await UserRepository(session).update_profile(user.id, weight_kg=Decimal(80))
    other = await UserRepository(session).create(telegram_id=2002, username="other")
    await UserRepository(session).update_profile(other.id, weight_kg=Decimal(60))
    foreign_id = (await _call(session, other.telegram_id, "GET", f"{URL}?metric=weight_kg")).json()["items"][0]["id"]

    assert (await _call(session, user.telegram_id, "PATCH", f"{URL}/{foreign_id}", {"value": "70"})).status_code == 404
    assert (await _call(session, user.telegram_id, "DELETE", f"{URL}/{foreign_id}")).status_code == 404
    await session.refresh(other)
    assert other.weight_kg == Decimal("60.00")


async def test_validation(session, user: User):
    await UserRepository(session).update_profile(user.id, weight_kg=Decimal(80), height_cm=180)
    entry_id = (await _call(session, user.telegram_id, "GET", f"{URL}?metric=weight_kg")).json()["items"][0]["id"]

    bad_bodies = [
        {"metric": "weight_kg", "value": "0"},
        {"metric": "weight_kg", "value": "9999"},
        {"metric": "height_cm", "value": "180.5"},
        {"metric": "body_fat", "value": "20"},
        {"metric": "weight_kg", "value": "80", "measured_at": (datetime.now(UTC) + timedelta(days=30)).isoformat()},
    ]
    for body in bad_bodies:
        assert (await _call(session, user.telegram_id, "POST", URL, body)).status_code == 422, body
    assert (await _call(session, user.telegram_id, "PATCH", f"{URL}/{entry_id}", {"value": "-5"})).status_code == 422
    assert (await _call(session, user.telegram_id, "GET", f"{URL}?metric=body_fat")).status_code == 422


async def test_unknown_user_is_404(session):
    assert (await _call(session, 424242, "GET", f"{URL}?metric=weight_kg")).status_code == 404
