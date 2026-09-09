"""GET /api/gto (issue #71) — разряд ГТО по подтягиванию, отдельная
концепция от обычных ачивок: пересчитывается на лету из пола/возраста/
лучшего max_reps, ничего не пишется в БД (см. app/domain/gto.py)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

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


async def _get_gto(session, telegram_id: int) -> dict:
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/gto")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    return response.json()


async def _record_workout(session, user_id: int, *, max_reps_a: int, max_reps_b: int, performed_at: datetime):
    baseline = await BaselineRepository(session).create(user_id=user_id, performed_at=performed_at, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user_id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user_id, workout_set_id=workout_set.id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=max_reps_a),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=max_reps_b),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )


def _birth_date_for_exact_age(years: int, today: date) -> date:
    return date(today.year - years, today.month, today.day)


async def test_gto_for_unknown_telegram_id_is_not_onboarded(session):
    body = await _get_gto(session, telegram_id=71001)
    assert body["applicable"] is False
    assert body["reason"] == "not_onboarded"


async def test_gto_for_female_is_only_male(session):
    user = await UserRepository(session).create(telegram_id=71002, username="f")
    await UserRepository(session).update_profile(
        user.id, gender=Gender.FEMALE, birth_date=_birth_date_for_exact_age(22, datetime.now(UTC).date()),
    )

    body = await _get_gto(session, telegram_id=user.telegram_id)

    assert body == {
        "applicable": False, "reason": "only_male", "age": None, "step_number": None, "rank": None,
        "best_max_reps": None, "bronze_threshold": None, "silver_threshold": None, "gold_threshold": None,
        "next_rank": None, "reps_to_next_rank": None,
    }


async def test_gto_missing_birth_date(session):
    user = await UserRepository(session).create(telegram_id=71003, username="m")
    await UserRepository(session).update_profile(user.id, gender=Gender.MALE)

    body = await _get_gto(session, telegram_id=user.telegram_id)

    assert body["applicable"] is False
    assert body["reason"] == "missing_birth_date"


async def test_gto_no_workouts_yet(session):
    user = await UserRepository(session).create(telegram_id=71004, username="m2")
    today = datetime.now(UTC).date()
    await UserRepository(session).update_profile(
        user.id, gender=Gender.MALE, birth_date=_birth_date_for_exact_age(22, today),
    )

    body = await _get_gto(session, telegram_id=user.telegram_id)

    assert body["applicable"] is False
    assert body["reason"] == "no_workouts"
    assert body["age"] == 22
    assert body["step_number"] == 8


async def test_gto_rank_computed_from_best_max_reps_across_blocks(session):
    """8 ступень (20-24), подтверждённые нормативы: золото=16, серебро=13,
    бронза=9. Лучший результат должен браться по максимуму из ДВУХ блоков
    (block_b здесь выше block_a) — тот же принцип агрегации, что
    unlock_history_achievements использует для MAX_REPS_PLUS_TEN."""
    user = await UserRepository(session).create(telegram_id=71005, username="m3")
    today = datetime.now(UTC).date()
    await UserRepository(session).update_profile(
        user.id, gender=Gender.MALE, birth_date=_birth_date_for_exact_age(22, today),
    )
    await _record_workout(
        session, user.id, max_reps_a=10, max_reps_b=13, performed_at=datetime.now(UTC) - timedelta(days=1),
    )

    body = await _get_gto(session, telegram_id=user.telegram_id)

    assert body["applicable"] is True
    assert body["best_max_reps"] == 13
    assert body["rank"] == "silver"
    assert body["next_rank"] == "gold"
    assert body["reps_to_next_rank"] == 3
    assert body["bronze_threshold"] == 9
    assert body["silver_threshold"] == 13
    assert body["gold_threshold"] == 16


async def test_gto_norm_data_missing_for_step_16(session):
    user = await UserRepository(session).create(telegram_id=71006, username="m4")
    today = datetime.now(UTC).date()
    await UserRepository(session).update_profile(
        user.id, gender=Gender.MALE, birth_date=_birth_date_for_exact_age(62, today),
    )
    await _record_workout(session, user.id, max_reps_a=10, max_reps_b=10, performed_at=datetime.now(UTC))

    body = await _get_gto(session, telegram_id=user.telegram_id)

    assert body["applicable"] is False
    assert body["reason"] == "norm_data_missing"
    assert body["step_number"] == 16
