"""GET /api/wsf (issue #104) — разряд WSF по многоповторным подтягиваниям
с отягощением, вторая система оценки рядом с ГТО (см. tests/test_web/test_gto.py
для аналогичного паттерна, app/domain/wsf.py для самого расчёта)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from app.db.models import Gender
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


async def _get_wsf(session, telegram_id: int) -> dict:
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/wsf")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    return response.json()


async def _record_weighted_workout(
    session, user_id: int, *, block_b_max_reps: int, block_b_equipment_value, performed_at: datetime,
):
    baseline = await BaselineRepository(session).create(user_id=user_id, performed_at=performed_at, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user_id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user_id, workout_set_id=workout_set.id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(), max_reps=block_b_max_reps),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=block_b_equipment_value,
    )


async def test_wsf_for_unknown_telegram_id_is_not_onboarded(session):
    body = await _get_wsf(session, telegram_id=104001)
    assert body["applicable"] is False
    assert body["reason"] == "not_onboarded"


async def test_wsf_missing_gender_and_weight(session):
    user = await UserRepository(session).create(telegram_id=104002, username="w1")

    body = await _get_wsf(session, telegram_id=user.telegram_id)

    assert body["applicable"] is False
    assert body["reason"] == "missing_gender"


async def test_wsf_missing_weight(session):
    user = await UserRepository(session).create(telegram_id=104003, username="w2")
    await UserRepository(session).update_profile(user.id, gender=Gender.MALE)

    body = await _get_wsf(session, telegram_id=user.telegram_id)

    assert body["applicable"] is False
    assert body["reason"] == "missing_weight"


async def test_wsf_no_workouts_yet(session):
    user = await UserRepository(session).create(telegram_id=104004, username="w3")
    await UserRepository(session).update_profile(user.id, gender=Gender.MALE, weight_kg=Decimal(58))

    body = await _get_wsf(session, telegram_id=user.telegram_id)

    assert body["applicable"] is False
    assert body["reason"] == "no_workouts"
    assert body["weight_category"] == "60"


async def test_wsf_norm_data_missing_for_women_at_uncovered_step(session):
    user = await UserRepository(session).create(telegram_id=104005, username="w4")
    await UserRepository(session).update_profile(user.id, gender=Gender.FEMALE, weight_kg=Decimal(50))
    await _record_weighted_workout(
        session, user.id, block_b_max_reps=10, block_b_equipment_value=Decimal(30), performed_at=datetime.now(UTC),
    )

    body = await _get_wsf(session, telegram_id=user.telegram_id)

    assert body["applicable"] is False
    assert body["reason"] == "norm_data_missing"
    assert body["weight_category"] == "52"


async def test_wsf_rank_computed_from_best_set_with_weight_step_rounded_down(session):
    # non_tested/15/men/60: elite23 msmk18 ms14 kms12 i11 ii10 iii9 (см.
    # app/domain/wsf.py, wsf_multirep_norms.json). +23 кг -> ступень 15.
    user = await UserRepository(session).create(telegram_id=104006, username="w5")
    await UserRepository(session).update_profile(user.id, gender=Gender.MALE, weight_kg=Decimal(58))
    await _record_weighted_workout(
        session, user.id, block_b_max_reps=10, block_b_equipment_value=Decimal(23),
        performed_at=datetime.now(UTC) - timedelta(days=1),
    )

    body = await _get_wsf(session, telegram_id=user.telegram_id)

    assert body["applicable"] is True
    assert body["weight_category"] == "60"
    assert body["added_weight_step_kg"] == "15"
    # equipment_value идёт через колонку Numeric(5,2) — при чтении из БД
    # нормализуется до двух знаков после запятой (тот же эффект, что "-20.00"
    # в tests/test_web/test_progress.py для той же колонки).
    assert body["actual_added_weight_kg"] == "23.00"
    assert body["rank"] == "ii"
    assert body["best_reps"] == 10
    assert body["next_rank"] == "i"
    assert body["reps_to_next_rank"] == 1
