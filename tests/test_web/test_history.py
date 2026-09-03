"""GET /api/history — вкладка "История" Mini App (issue #50, волна 1):
те же факты, что печатает app.bot.handlers.history.handle_show_history
(тот же WorkoutRepository.list_for_user, тот же format_block_result),
структурированные под карточки вместо единого текстового блока бота."""

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


async def _get_history(session, telegram_id: int, *, offset: int = 0, limit: int = 20) -> dict:
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/history", params={"offset": offset, "limit": limit})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    return response.json()


async def _record_workout(session, user_id: int, workout_set_id: int, performed_at: datetime, *, working_a: int = 11):
    await WorkoutRepository(session).record_workout(
        user_id=user_id, workout_set_id=workout_set_id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=(working_a, working_a, working_a), max_reps=working_a + 1),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=Decimal("20.0"),
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=Decimal("20.0"),
    )


async def test_history_for_unknown_telegram_id_is_empty(session):
    body = await _get_history(session, telegram_id=52001)
    assert body == {"items": [], "has_more": False}


async def test_history_for_user_without_workouts(session):
    user = await UserRepository(session).create(telegram_id=52002, username="fresh")
    body = await _get_history(session, telegram_id=user.telegram_id)
    assert body == {"items": [], "has_more": False}


async def test_history_returns_newest_first_with_target_only_on_latest(session):
    user = await UserRepository(session).create(telegram_id=52003, username="active")
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime.now(UTC) - timedelta(days=10), reps=10,
    )
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)

    older = datetime.now(UTC) - timedelta(days=5)
    newer = datetime.now(UTC) - timedelta(days=1)
    await _record_workout(session, user.id, workout_set.id, older, working_a=11)
    await _record_workout(session, user.id, workout_set.id, newer, working_a=12)

    body = await _get_history(session, telegram_id=user.telegram_id)

    assert body["has_more"] is False
    assert len(body["items"]) == 2
    latest, previous = body["items"]
    assert latest["performed_at"] == newer.date().isoformat()
    assert latest["target_a"] is not None
    assert latest["target_b"] is not None
    assert previous["performed_at"] == older.date().isoformat()
    assert previous["target_a"] is None
    assert previous["target_b"] is None
    assert latest["result_a"] == "12, 12, 12, максимум 13"


async def test_history_paginates_with_offset_and_limit(session):
    user = await UserRepository(session).create(telegram_id=52004, username="prolific")
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime.now(UTC) - timedelta(days=30), reps=10,
    )
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)

    for day_offset in range(25, 0, -1):
        await _record_workout(session, user.id, workout_set.id, datetime.now(UTC) - timedelta(days=day_offset))

    first_page = await _get_history(session, telegram_id=user.telegram_id, offset=0, limit=20)
    assert len(first_page["items"]) == 20
    assert first_page["has_more"] is True

    second_page = await _get_history(session, telegram_id=user.telegram_id, offset=20, limit=20)
    assert len(second_page["items"]) == 5
    assert second_page["has_more"] is False

    first_dates = {item["performed_at"] for item in first_page["items"]}
    second_dates = {item["performed_at"] for item in second_page["items"]}
    assert first_dates.isdisjoint(second_dates)


async def test_history_marks_backdated_workouts(session):
    user = await UserRepository(session).create(telegram_id=52005, username="backdater")
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime.now(UTC) - timedelta(days=10), reps=10,
    )
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_backdated_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC) - timedelta(days=3),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=Decimal("20.0"),
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=Decimal("20.0"),
    )

    body = await _get_history(session, telegram_id=user.telegram_id)

    assert body["items"][0]["is_backdated"] is True
