"""GET /api/leaderboard, PUT /api/leaderboard/display-name (issue #67) —
три переключаемые метрики лидерборда плюс необязательное отображаемое имя
(NULL/дефолт — анонимно)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import EquipmentType
from app.domain.session import BlockLog
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


async def _get(session, telegram_id: int, path: str) -> dict:
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(path)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    return response.json()


async def _put(session, telegram_id: int, path: str, body: dict) -> tuple[int, dict]:
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(path, json=body)
    finally:
        app.dependency_overrides.clear()
    return response.status_code, response.json()


async def _record_workout(session, user_id: int):
    baseline = await BaselineRepository(session).create(user_id=user_id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user_id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user_id,
        workout_set_id=workout_set.id,
        performed_at=datetime.now(UTC),
        block_a_reps=BlockLog(working_reps=(20, 20, 20), max_reps=25),
        block_b_reps=BlockLog(working_reps=(5, 5, 5, 5), max_reps=6),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )


async def test_leaderboard_for_unknown_telegram_id_is_empty(session):
    body = await _get(session, telegram_id=68001, path="/api/leaderboard?metric=max_reps")
    assert body == {"metric": "max_reps", "entries": [], "my_display_name": None, "my_rank": None}


async def test_leaderboard_entry_defaults_to_anonymous_label(session):
    user = await UserRepository(session).create(telegram_id=68002, username="anon")
    await _record_workout(session, user.id)

    body = await _get(session, telegram_id=user.telegram_id, path="/api/leaderboard?metric=max_reps")
    assert len(body["entries"]) == 1
    assert body["entries"][0]["display_name"] == "Аноним"
    assert body["entries"][0]["is_current_user"] is True
    assert body["my_rank"] == 1
    assert body["my_display_name"] is None


async def test_leaderboard_invalid_age_bucket_is_rejected(session):
    _override_dependencies(session, 68003)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/leaderboard?metric=max_reps&age_bucket=not_a_bucket")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 400


async def test_update_display_name_then_appears_in_leaderboard(session):
    user = await UserRepository(session).create(telegram_id=68004, username="named")
    await _record_workout(session, user.id)

    status_code, put_body = await _put(
        session, user.telegram_id, "/api/leaderboard/display-name", {"display_name": "Штанга Иваныч"},
    )
    assert status_code == 200
    assert put_body == {"display_name": "Штанга Иваныч"}

    body = await _get(session, telegram_id=user.telegram_id, path="/api/leaderboard?metric=max_reps")
    assert body["entries"][0]["display_name"] == "Штанга Иваныч"
    assert body["my_display_name"] == "Штанга Иваныч"


async def test_update_display_name_empty_string_clears_to_anonymous(session):
    user = await UserRepository(session).create(telegram_id=68005, username="renamed")
    await UserRepository(session).set_leaderboard_display_name(user.id, "Старое Имя")

    status_code, put_body = await _put(
        session, user.telegram_id, "/api/leaderboard/display-name", {"display_name": "   "},
    )
    assert status_code == 200
    assert put_body == {"display_name": None}


async def test_update_display_name_for_unknown_user_is_404(session):
    status_code, _ = await _put(session, 68006, "/api/leaderboard/display-name", {"display_name": "X"})
    assert status_code == 404


async def test_max_weight_value_is_decimal_string(session):
    user = await UserRepository(session).create(telegram_id=68007, username="lifter")
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id,
        workout_set_id=workout_set.id,
        performed_at=datetime.now(UTC),
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=12),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=Decimal("20.0"),
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=Decimal("17.5"),
    )

    body = await _get(session, telegram_id=user.telegram_id, path="/api/leaderboard?metric=max_weight")
    # Numeric(5, 2) на blocks.equipment_value сохраняет масштаб — "17.50",
    # не "17.5" (тот же формат, что и у остальных Decimal-полей проекта).
    assert body["entries"][0]["value"] == "17.50"
