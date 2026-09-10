"""GET /api/progress — вкладка "Прогресс" Mini App (issue #82: переделано
с плана на факт, была история — issue #50, волна 2, строилась по
target_after). Три переключаемые метрики (metric=max_reps|volume|strength),
все — факт по BlockLog, не плановая цель прогрессии."""

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


async def _get_progress(session, telegram_id: int, metric: str = "max_reps") -> dict:
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/progress?metric={metric}")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    return response.json()


async def test_progress_for_unknown_telegram_id_is_empty(session):
    body = await _get_progress(session, telegram_id=53001)
    assert body == {"metric": "max_reps", "points": []}


async def test_progress_for_user_without_workouts(session):
    user = await UserRepository(session).create(telegram_id=53002, username="fresh")
    body = await _get_progress(session, telegram_id=user.telegram_id)
    assert body == {"metric": "max_reps", "points": []}


async def _record_three_workouts(session, telegram_id: int):
    """Три тренировки с намеренно разным снарядом блока Б (резина 20кг ->
    отягощение 7.5кг -> "австралийские" подтягивания без кг вовсе) — нужны
    для проверки всех трёх ветвей метрики "Сила": знак резины/отягощения
    на единой шкале и пропуск AUSTRALIAN (там to_signed_load не определена).

    Числа посчитаны руками, не выведены из тестируемого кода:
    - workout 1: блок A сумма 11+11+11+12=45, лучший подход 12;
      блок Б сумма 4+4+4+4+5=21, лучший подход 5; резина 20кг -> сила -20.00.
    - workout 2: блок A сумма 14*3+15=57, лучший подход 15;
      блок Б сумма 5*4+6=26, лучший подход 6; отягощение 7.5кг -> сила 7.50.
    - workout 3: блок A сумма 16*3+17=65, лучший подход 17;
      блок Б сумма 3*4+4=16, лучший подход 4; AUSTRALIAN -> сила не определена (null).
    """
    user = await UserRepository(session).create(telegram_id=telegram_id, username="active")
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime.now(UTC) - timedelta(days=10), reps=10,
    )
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    workouts = WorkoutRepository(session)

    first_at = datetime.now(UTC) - timedelta(days=5)
    second_at = datetime.now(UTC) - timedelta(days=3)
    third_at = datetime.now(UTC) - timedelta(days=1)

    await workouts.record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=first_at,
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=Decimal("20.0"),
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=Decimal("20.0"),
    )
    await workouts.record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=second_at,
        block_a_reps=BlockLog(working_reps=(14, 14, 14), max_reps=15),
        block_b_reps=BlockLog(working_reps=(5, 5, 5, 5), max_reps=6),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=Decimal("20.0"),
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=Decimal("7.5"),
    )
    await workouts.record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=third_at,
        block_a_reps=BlockLog(working_reps=(16, 16, 16), max_reps=17),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=4),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=Decimal("20.0"),
        block_b_equipment_type=EquipmentType.AUSTRALIAN, block_b_equipment_value=None,
    )
    return user, workout_set, [first_at, second_at, third_at]


async def test_progress_max_reps_metric_is_best_set_not_target(session):
    user, workout_set, (first_at, second_at, third_at) = await _record_three_workouts(session, telegram_id=53003)

    body = await _get_progress(session, telegram_id=user.telegram_id, metric="max_reps")

    assert body["metric"] == "max_reps"
    assert body["points"] == [
        {"performed_at": first_at.date().isoformat(), "value_a": "12", "value_b": "5", "workout_set_id": workout_set.id},
        {"performed_at": second_at.date().isoformat(), "value_a": "15", "value_b": "6", "workout_set_id": workout_set.id},
        {"performed_at": third_at.date().isoformat(), "value_a": "17", "value_b": "4", "workout_set_id": workout_set.id},
    ]


async def test_progress_volume_metric_is_actual_reps_sum(session):
    user, workout_set, (first_at, second_at, third_at) = await _record_three_workouts(session, telegram_id=53004)

    body = await _get_progress(session, telegram_id=user.telegram_id, metric="volume")

    assert body["metric"] == "volume"
    assert body["points"] == [
        {"performed_at": first_at.date().isoformat(), "value_a": "45", "value_b": "21", "workout_set_id": workout_set.id},
        {"performed_at": second_at.date().isoformat(), "value_a": "57", "value_b": "26", "workout_set_id": workout_set.id},
        {"performed_at": third_at.date().isoformat(), "value_a": "65", "value_b": "16", "workout_set_id": workout_set.id},
    ]


async def test_progress_strength_metric_is_signed_load_of_block_b_only(session):
    user, workout_set, (first_at, second_at, third_at) = await _record_three_workouts(session, telegram_id=53005)

    body = await _get_progress(session, telegram_id=user.telegram_id, metric="strength")

    assert body["metric"] == "strength"
    assert body["points"] == [
        {"performed_at": first_at.date().isoformat(), "value_a": None, "value_b": "-20.00", "workout_set_id": workout_set.id},
        {"performed_at": second_at.date().isoformat(), "value_a": None, "value_b": "7.50", "workout_set_id": workout_set.id},
        {"performed_at": third_at.date().isoformat(), "value_a": None, "value_b": None, "workout_set_id": workout_set.id},
    ]
