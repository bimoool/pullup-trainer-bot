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
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
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


async def _patch(session, telegram_id: int, path: str, payload: dict):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.patch(path, json=payload)
    finally:
        app.dependency_overrides.clear()


async def _delete(session, telegram_id: int, path: str):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.delete(path)
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


# --- PATCH /api/equipment/band-items/{id} (issue #148) --------------------------------


async def test_update_band_item_for_unknown_telegram_id_is_404(session):
    response = await _patch(
        session, telegram_id=53030, path="/api/equipment/band-items/1", payload={"name": "Новое имя"},
    )
    assert response.status_code == 404


async def test_update_band_item_renames(session):
    user = await UserRepository(session).create(telegram_id=53031, username="renamer")
    item = await EquipmentItemRepository(session).create(user_id=user.id, name="Старое имя")

    response = await _patch(
        session, telegram_id=53031, path=f"/api/equipment/band-items/{item.id}", payload={"name": "Новое имя"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Новое имя"

    persisted = await EquipmentItemRepository(session).get_by_id(item.id)
    assert persisted.name == "Новое имя"


async def test_update_band_item_rejects_blank_name(session):
    user = await UserRepository(session).create(telegram_id=53032, username="blank-rename")
    item = await EquipmentItemRepository(session).create(user_id=user.id, name="Имя")

    response = await _patch(
        session, telegram_id=53032, path=f"/api/equipment/band-items/{item.id}", payload={"name": "   "},
    )
    assert response.status_code == 422


async def test_update_band_item_rejects_foreign_item(session):
    owner = await UserRepository(session).create(telegram_id=53033, username="owner")
    await UserRepository(session).create(telegram_id=53034, username="intruder")
    item = await EquipmentItemRepository(session).create(user_id=owner.id, name="Чужая")

    response = await _patch(
        session, telegram_id=53034, path=f"/api/equipment/band-items/{item.id}", payload={"name": "Захват"},
    )
    assert response.status_code == 404

    persisted = await EquipmentItemRepository(session).get_by_id(item.id)
    assert persisted.name == "Чужая"


# --- DELETE /api/equipment/band-items/{id} (issue #148) --------------------------------


async def test_delete_band_item_for_unknown_telegram_id_is_404(session):
    response = await _delete(session, telegram_id=53040, path="/api/equipment/band-items/1")
    assert response.status_code == 404


async def test_delete_band_item_removes_it(session):
    user = await UserRepository(session).create(telegram_id=53041, username="deleter")
    item = await EquipmentItemRepository(session).create(user_id=user.id, name="На удаление")

    response = await _delete(session, telegram_id=53041, path=f"/api/equipment/band-items/{item.id}")
    assert response.status_code == 200
    assert response.json()["name"] == "На удаление"

    assert await EquipmentItemRepository(session).get_by_id(item.id) is None


async def test_delete_band_item_rejects_foreign_item(session):
    owner = await UserRepository(session).create(telegram_id=53042, username="owner2")
    await UserRepository(session).create(telegram_id=53043, username="intruder2")
    item = await EquipmentItemRepository(session).create(user_id=owner.id, name="Чужая 2")

    response = await _delete(session, telegram_id=53043, path=f"/api/equipment/band-items/{item.id}")
    assert response.status_code == 404

    assert await EquipmentItemRepository(session).get_by_id(item.id) is not None


async def test_delete_band_item_already_used_in_workout_does_not_break_history(session):
    """issue #148 — резину, уже использованную в записанной тренировке,
    можно удалить (FK ON DELETE SET NULL, не RESTRICT): DELETE не падает
    500, а следующая тренировка для этого же блока честно наследует "снаряд
    band, резина не выбрана" (item_id null), не тянет несуществующий id.

    Проверяется через WorkoutRepository.resolve_next_targets напрямую, не
    через GET /api/workout/plan — тот в этом же тесте упёрся бы в
    MIN_REST_DAYS (та же календарная дата, что и только что записанная
    тренировка), а тут важна не готовность к тренировке, а то, что
    наследуется как снаряд."""
    user = await UserRepository(session).create(telegram_id=53044, username="new-on-band-2")
    now = datetime.now(UTC)
    await BaselineRepository(session).create(user_id=user.id, performed_at=now, reps=2)
    await UserRepository(session).complete_onboarding(user.id, now)
    await SubscriptionService(session).start_trial(user.id, now=now)

    created = await _post(
        session, telegram_id=53044, path="/api/equipment/band-items",
        payload={"name": "Единственная резина", "resistance_kg": "20"},
    )
    item_id = created.json()["id"]

    submit_response = await _post(
        session, telegram_id=53044, path="/api/workout/submit",
        payload={
            "block_a_working_reps": [2, 2, 2], "block_a_max_reps": 3,
            "block_b_working_reps": [3, 3, 3, 3], "block_b_max_reps": 3,
            "block_a_actual_band_item_id": item_id, "block_b_actual_band_item_id": item_id,
            "comment": None, "confirm_anomalies": False,
        },
    )
    assert submit_response.status_code == 200

    delete_response = await _delete(session, telegram_id=53044, path=f"/api/equipment/band-items/{item_id}")
    assert delete_response.status_code == 200

    user_row = await UserRepository(session).get_by_telegram_id(53044)
    # Тестовая фикстура (см. _override_dependencies выше) переиспользует
    # один и тот же AsyncSession между "запросами" внутри теста — Block,
    # уже загруженный в identity map во время submit_workout, сам по себе
    # не узнает про ON DELETE SET NULL, применённый Postgres к его строке
    # (SQLAlchemy не отслеживает FK-каскады на уровне БД для уже
    # загруженных Python-объектов). В реальном приложении у каждого HTTP-
    # запроса своя сессия — expire_all() здесь только имитирует "следующий
    # запрос увидит настоящее состояние БД", не часть тестируемого кода.
    session.expire_all()

    target_a_state, target_b_state = await WorkoutRepository(session).resolve_next_targets(user_row.id)
    # Резина, унаследованная с прошлой тренировки, была удалена — сервер не
    # подставляет несуществующий id молча, снаряд остаётся band, но без
    # item_id (фронтенд в этом случае требует выбрать/завести резину заново).
    assert target_a_state.equipment_type == EquipmentType.BAND
    assert target_a_state.equipment_item_id is None
    assert target_b_state.equipment_type == EquipmentType.BAND
    assert target_b_state.equipment_item_id is None
