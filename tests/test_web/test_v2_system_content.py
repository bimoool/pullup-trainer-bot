"""Системный контент (issue #296, D1-D3): публичная библиотека без служебных упражнений,
каталог готовых тренировок и их исполнимость.

Контент ставит data-миграция a4c8e1f7b2d9; conftest чистит programs/exercises/complexes между
тестами, поэтому здесь миграционный сид вызывается напрямую (`seed_system_content`) на сессии
теста — тот же код, что выполняет `alembic upgrade head` (end-to-end по deploy — в
tests/test_scripts/test_system_content_migration.py)."""

import importlib.util
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.models_program import Complex, Exercise
from app.db.repositories.programs import ProgramRepository
from app.db.repositories.users import UserRepository
from app.domain.multi_program import is_internal_exercise_subcategory
from app.domain.workout_protocol import UserWorkoutProtocol
from tests.test_web._v2_client import v2_get, v2_patch, v2_post, v2_put

_MIGRATION = (
    Path(__file__).resolve().parents[2] / "app/db/migrations/versions/a4c8e1f7b2d9_system_content_seed.py"
)

LIBRARY = {
    "Подтягивания", "Подтягивания с резиной", "Подтягивания с отягощением", "Австралийские подтягивания",
    "Лопаточные подтягивания", "Вис на турнике", "Планка", "Отжимания",
}
WORKOUTS = {"Максимум подтягиваний", "W-лесенка", "3 минуты подтягиваний", "Объём ×5"}


def _load_migration():
    spec = importlib.util.spec_from_file_location("system_content_migration", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def ship_system_content(session: AsyncSession) -> None:
    """Выполняет сид миграции на соединении сессии теста (в её транзакции)."""
    module = _load_migration()
    await session.run_sync(lambda sync_session: module.seed_system_content(sync_session.connection()))


async def _user(session: AsyncSession, telegram_id: int = 940001) -> User:
    users = UserRepository(session)
    user = await users.create(telegram_id=telegram_id, username=f"u{telegram_id}")
    await users.complete_onboarding(user.id, datetime.now(UTC))
    return user


async def _catalog(session: AsyncSession, user: User) -> dict[str, dict]:
    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/workouts/catalog")
    assert response.status_code == 200
    return {w["title"]: w for w in response.json()["workouts"]}


def test_internal_subcategory_boundary():
    assert is_internal_exercise_subcategory("block_a")
    assert is_internal_exercise_subcategory("block_b")
    assert is_internal_exercise_subcategory("elective_w_ladder")
    assert not is_internal_exercise_subcategory(None)
    assert not is_internal_exercise_subcategory("electrical")  # префикс — «elective_», не «elect…»


async def test_library_is_exactly_the_agreed_set_and_hides_internal_exercises(session: AsyncSession):
    await ship_system_content(session)
    user = await _user(session)

    # Служебные записи есть в БД (история и программа на них ссылаются) ...
    internal = (await session.execute(
        select(Exercise.name).where(Exercise.owner_user_id.is_(None), Exercise.subcategory.is_not(None)),
    )).scalars().all()
    assert len([n for n in internal if n.startswith("Факультатив")]) == 4
    assert {"Подтягивания — объём", "Подтягивания — сила"} <= set(internal)

    # ... но публичная библиотека свежего пользователя — ровно согласованный набор.
    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/exercises")
    assert response.status_code == 200
    exercises = response.json()["exercises"]
    assert {e["name"] for e in exercises} == LIBRARY
    assert len(exercises) == len(LIBRARY), "дублей в библиотеке нет"
    by_name = {e["name"]: e for e in exercises}
    assert by_name["Вис на турнике"]["metric_type"] == "time"
    assert all(e["subcategory"] is None for e in exercises)


async def test_own_user_exercise_with_internal_looking_name_is_still_listed(session: AsyncSession):
    # Граница — по subcategory, не по названию: свой «Факультатив — …» без subcategory не прячется.
    await ship_system_content(session)
    user = await _user(session)
    response = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/exercises", payload={"name": "Факультатив мой"})
    assert response.status_code == 200
    listed = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/exercises")
    assert "Факультатив мой" in {e["name"] for e in listed.json()["exercises"]}


async def test_internal_exercises_cannot_be_attached_to_plan_but_library_can(session: AsyncSession):
    await ship_system_content(session)
    user = await _user(session)
    repo = ProgramRepository(session)
    rows = {e.name: e for e in (await session.execute(select(Exercise).where(Exercise.owner_user_id.is_(None)))).scalars()}

    for name in ("Факультатив — подтягивания W", "Подтягивания — объём"):
        assert await repo.get_plan_attachable_exercise_for_user(rows[name].id, user.id) is None
        response = await v2_post(
            session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
            payload={"exercise_id": rows[name].id, "count_per_week": 1},
        )
        assert response.status_code == 404
    assert await repo.get_plan_attachable_exercise_for_user(rows["Подтягивания"].id, user.id) is not None


async def test_catalog_lists_the_four_system_workouts_and_my_workouts_stays_own_only(session: AsyncSession):
    await ship_system_content(session)
    user = await _user(session)
    other = await _user(session, 940002)
    foreign = Complex(name="Чужая", source_type="user", owner_user_id=other.id)
    own = Complex(name="Моя", source_type="user", owner_user_id=user.id)
    session.add_all([foreign, own])
    await session.flush()

    catalog = await _catalog(session, user)
    assert set(catalog) == WORKOUTS  # ни чужих, ни своих
    assert all(w["source_type"] == "system" and w["owner_user_id"] is None for w in catalog.values())
    assert all(len(w["items"]) == 1 and w["items"][0]["exercise_name"] == "Подтягивания" for w in catalog.values())

    mine = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/workouts")
    assert [w["title"] for w in mine.json()["workouts"]] == ["Моя"]


async def test_catalog_requires_a_known_user(session: AsyncSession):
    await ship_system_content(session)
    response = await v2_get(session, telegram_id=999_999_001, path="/api/v2/workouts/catalog")
    assert response.status_code in (401, 403, 404)


async def test_system_workout_protocols_are_valid_definitions(session: AsyncSession):
    await ship_system_content(session)
    user = await _user(session)
    adapter = TypeAdapter(UserWorkoutProtocol)
    catalog = await _catalog(session, user)

    protocols = {title: adapter.validate_python(w["items"][0]["protocol"]) for title, w in catalog.items()}
    assert protocols["Максимум подтягиваний"].type == "max_effort"
    assert protocols["W-лесенка"].type == "reps_sets"
    assert protocols["3 минуты подтягиваний"].type == "interval"
    assert protocols["3 минуты подтягиваний"].total_duration_seconds == 180
    assert protocols["Объём ×5"].type == "reps_sets"


@pytest.mark.parametrize("title", sorted(WORKOUTS))
async def test_every_system_workout_opens_and_starts(session: AsyncSession, title: str):
    await ship_system_content(session)
    user = await _user(session)
    workout = (await _catalog(session, user))[title]

    detail = await v2_get(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout['id']}")
    assert detail.status_code == 200
    assert detail.json()["source_type"] == "system"

    started = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={"client_session_id": str(uuid.uuid4()), "workout_id": workout["id"]},
    )
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["status"] == "started"
    assert body["title"] == title
    assert body["blocks"], "в снимке старта есть блок"


async def test_system_workout_can_be_added_to_plan_but_not_edited(session: AsyncSession):
    await ship_system_content(session)
    user = await _user(session)
    workout = (await _catalog(session, user))["Объём ×5"]

    added = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/plan-items",
        payload={"complex_id": workout["id"], "count_per_week": 1},
    )
    assert added.status_code == 200, added.text

    renamed = await v2_patch(session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout['id']}", payload={"title": "Взлом"})
    assert renamed.status_code == 404
    item_id = workout["items"][0]["id"]
    edited = await v2_patch(
        session, telegram_id=user.telegram_id, path=f"/api/v2/workouts/{workout['id']}/items/{item_id}",
        payload={"protocol": workout["items"][0]["protocol"]},
    )
    assert edited.status_code == 404


async def test_system_workout_can_be_favorited(session: AsyncSession):
    await ship_system_content(session)
    user = await _user(session)
    workout = (await _catalog(session, user))["W-лесенка"]

    put = await v2_put(session, telegram_id=user.telegram_id, path=f"/api/v2/favorites/workout/{workout['id']}")
    assert put.status_code == 204
    favorites = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/favorites")).json()["favorites"]
    assert [(f["target_type"], f["title"], f["subtitle"]) for f in favorites] == [("workout", "W-лесенка", "Готовая тренировка")]


async def test_system_content_is_user_independent(session: AsyncSession):
    """Сид не знает пользователей: ни плана, ни включений, ни сессий (и работает на пустой таблице users)."""
    await ship_system_content(session)
    assert await session.scalar(select(Complex.id).where(Complex.owner_user_id.is_not(None))) is None
