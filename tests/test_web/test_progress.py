"""GET /api/progress — вкладка "Прогресс" Mini App (issue #50, волна 2):
цель за подход по тренировкам во времени, для блока A и Б отдельно.
WorkoutRepository.list_records_for_user отдаёт уже посчитанный
target_after (app.domain.progression) — эндпойнт его не пересчитывает."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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


async def _get_progress(session, telegram_id: int) -> dict:
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/progress")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    return response.json()


async def test_progress_for_unknown_telegram_id_is_empty(session):
    body = await _get_progress(session, telegram_id=53001)
    assert body == {"points": []}


async def test_progress_for_user_without_workouts(session):
    user = await UserRepository(session).create(telegram_id=53002, username="fresh")
    body = await _get_progress(session, telegram_id=user.telegram_id)
    assert body == {"points": []}


async def test_progress_reports_target_after_per_workout_in_order(session):
    user = await UserRepository(session).create(telegram_id=53003, username="active")
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime.now(UTC) - timedelta(days=10), reps=10,
    )
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    workouts = WorkoutRepository(session)

    first_at = datetime.now(UTC) - timedelta(days=5)
    second_at = datetime.now(UTC) - timedelta(days=1)
    first = await workouts.record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=first_at,
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=Decimal("20.0"),
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=Decimal("20.0"),
    )
    second = await workouts.record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=second_at,
        block_a_reps=BlockLog(working_reps=(14, 14, 14), max_reps=15),
        block_b_reps=BlockLog(working_reps=(5, 5, 5, 5), max_reps=6),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=Decimal("20.0"),
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=Decimal("20.0"),
    )
    first_block_a = next(b for b in first.blocks if b.block_type.value == "a")
    first_block_b = next(b for b in first.blocks if b.block_type.value == "b")
    second_block_a = next(b for b in second.blocks if b.block_type.value == "a")
    second_block_b = next(b for b in second.blocks if b.block_type.value == "b")

    body = await _get_progress(session, telegram_id=user.telegram_id)

    assert body["points"] == [
        {
            "performed_at": first_at.date().isoformat(),
            "target_a": first_block_a.target_after,
            "target_b": first_block_b.target_after,
            "workout_set_id": workout_set.id,
        },
        {
            "performed_at": second_at.date().isoformat(),
            "target_a": second_block_a.target_after,
            "target_b": second_block_b.target_after,
            "workout_set_id": workout_set.id,
        },
    ]
