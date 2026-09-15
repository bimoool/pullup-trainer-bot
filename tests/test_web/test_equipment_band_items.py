"""GET/POST /api/equipment/band-items (issue #124, PR 3) — последний
бот-only кусок онбординга, перенесённый в Mini App: заведение личной резины
через тот же EquipmentItemRepository.create, что _create_band_item_and_advance/
_create_standalone_band_item бота (app/bot/handlers/equipment.py) уже
вызывают, не отдельная веб-копия. Отдельный тест на полный сценарий первой
тренировки на резине (PR 2 довёл GET /api/workout/plan до status="ready" со
снарядом band и пустым band_items — этот PR закрывает последний тупик:
POST /api/equipment/band-items создаёт резину, которую затем можно передать
в POST /api/workout/submit, как и обычный выбор резины issue #48)."""

from dataclasses import dataclass
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient

from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.users import UserRepository
from app.services.subscription import SubscriptionService
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


async def _get(session, telegram_id: int, path: str):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get(path)
    finally:
        app.dependency_overrides.clear()


async def _post(session, telegram_id: int, path: str, payload: dict):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post(path, json=payload)
    finally:
        app.dependency_overrides.clear()


# --- GET /api/equipment/band-items ---------------------------------------------------


async def test_list_band_items_for_unknown_telegram_id_is_404(session):
    response = await _get(session, telegram_id=53001, path="/api/equipment/band-items")
    assert response.status_code == 404


async def test_list_band_items_returns_only_own_items(session):
    user = await UserRepository(session).create(telegram_id=53002, username="own")
    other = await UserRepository(session).create(telegram_id=53003, username="other")
    await EquipmentItemRepository(session).create(user_id=user.id, name="Красная", resistance_kg=None)
    await EquipmentItemRepository(session).create(user_id=other.id, name="Чужая", resistance_kg=None)

    response = await _get(session, telegram_id=53002, path="/api/equipment/band-items")
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["name"] for item in items] == ["Красная"]


# --- POST /api/equipment/band-items --------------------------------------------------


async def test_create_band_item_for_unknown_telegram_id_is_404(session):
    response = await _post(
        session, telegram_id=53010, path="/api/equipment/band-items", payload={"name": "Синяя", "resistance_kg": None},
    )
    assert response.status_code == 404


async def test_create_band_item_writes_through_repository(session):
    user = await UserRepository(session).create(telegram_id=53011, username="creator")

    response = await _post(
        session, telegram_id=53011, path="/api/equipment/band-items",
        payload={"name": "Фиолетовая", "resistance_kg": "15.5"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Фиолетовая"
    assert body["resistance_kg"] == "15.5"

    items = await EquipmentItemRepository(session).list_for_user(user.id)
    assert len(items) == 1
    assert items[0].id == body["id"]
    assert items[0].name == "Фиолетовая"


async def test_create_band_item_without_resistance_is_allowed(session):
    await UserRepository(session).create(telegram_id=53012, username="unsure")

    response = await _post(
        session, telegram_id=53012, path="/api/equipment/band-items",
        payload={"name": "Не знаю какая", "resistance_kg": None},
    )
    assert response.status_code == 200
    assert response.json()["resistance_kg"] is None


async def test_create_band_item_rejects_blank_name(session):
    await UserRepository(session).create(telegram_id=53013, username="blank")

    response = await _post(
        session, telegram_id=53013, path="/api/equipment/band-items", payload={"name": "   ", "resistance_kg": None},
    )
    assert response.status_code == 422


async def test_create_band_item_rejects_non_positive_resistance(session):
    await UserRepository(session).create(telegram_id=53014, username="neg")

    response = await _post(
        session, telegram_id=53014, path="/api/equipment/band-items",
        payload={"name": "Ok", "resistance_kg": "0"},
    )
    assert response.status_code == 422


async def test_create_band_item_appends_without_removing_existing(session):
    user = await UserRepository(session).create(telegram_id=53015, username="second")
    await EquipmentItemRepository(session).create(user_id=user.id, name="Первая", resistance_kg=None)

    response = await _post(
        session, telegram_id=53015, path="/api/equipment/band-items",
        payload={"name": "Вторая", "resistance_kg": None},
    )
    assert response.status_code == 200

    items = await EquipmentItemRepository(session).list_for_user(user.id)
    assert [item.name for item in items] == ["Первая", "Вторая"]


# --- Полный сценарий: первая тренировка на резине без единого шага в боте -----------


async def test_first_workout_on_band_can_be_completed_end_to_end_via_created_item(session):
    """Баг, который этот PR закрывает: до него GET /api/workout/plan для
    новичка со стартовым снарядом band(baseline=2, см. suggest_starting_
    equipment) отдавал пустой band_items и не оставлял способа завести
    резину без захода в бота — POST /api/workout/submit падал бы 400
    "Invalid band item for block A" на любой присланный item_id, потому
    что взять его было неоткуда. Здесь резина заводится через
    POST /api/equipment/band-items тем же HTTP-клиентом, что потом
    отправляет тренировку — целиком в Mini App."""
    user = await UserRepository(session).create(telegram_id=53020, username="new-on-band")
    now = datetime.now(UTC)
    await BaselineRepository(session).create(user_id=user.id, performed_at=now, reps=2)
    await UserRepository(session).complete_onboarding(user.id, now)
    await SubscriptionService(session).start_trial(user.id, now=now)

    plan_response = await _get(session, telegram_id=53020, path="/api/workout/plan")
    plan = plan_response.json()
    assert plan["status"] == "ready"
    assert plan["equipment_a"]["type"] == "band"
    assert plan["equipment_b"]["type"] == "band"
    assert plan["band_items"] == []

    created = await _post(
        session, telegram_id=53020, path="/api/equipment/band-items",
        payload={"name": "Моя первая резина", "resistance_kg": "20"},
    )
    assert created.status_code == 200
    item_id = created.json()["id"]

    submit_response = await _post(
        session, telegram_id=53020, path="/api/workout/submit",
        payload={
            "block_a_working_reps": [2, 2, 2], "block_a_max_reps": 3,
            "block_b_working_reps": [3, 3, 3, 3], "block_b_max_reps": 3,
            "block_a_actual_band_item_id": item_id, "block_b_actual_band_item_id": item_id,
            "comment": None, "confirm_anomalies": False,
        },
    )
    assert submit_response.status_code == 200
    body = submit_response.json()
    assert body["status"] == "ok"
    assert body["equipment_a"]["item_id"] == item_id
    assert body["equipment_b"]["item_id"] == item_id
