"""GET /api/analytics — аналитический блок вкладки "Прогресс" Mini App
(issue #66, п.2): те же app.domain.reports вызовы (weekly_summary/
current_equipment_progress/all_cycles_analytics) с теми же входными
данными, что кнопки "📊 Прогресс"/"📈 Аналитика по всем циклам" бота
(app/bot/handlers/reports.py), просто в JSON вместо готового текста."""

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


async def _get_analytics(session, telegram_id: int) -> dict:
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/analytics")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    return response.json()


async def test_analytics_for_unknown_telegram_id_has_no_data(session):
    body = await _get_analytics(session, telegram_id=54001)
    assert body == {
        "has_data": False, "weekly": None, "equipment_progress_a": None, "equipment_progress_b": None,
        "epley_progress": None, "total_volume": None, "cycle_count": None, "cycles": [],
    }


async def test_analytics_for_user_without_workouts_has_no_data(session):
    user = await UserRepository(session).create(telegram_id=54002, username="fresh")
    body = await _get_analytics(session, telegram_id=user.telegram_id)
    assert body["has_data"] is False


async def test_analytics_reports_weekly_summary_equipment_progress_and_cycles(session):
    user = await UserRepository(session).create(telegram_id=54003, username="active")
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime.now(UTC) - timedelta(days=10), reps=10,
    )
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    performed_at = datetime.now(UTC) - timedelta(days=3)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=Decimal("20.0"),
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=Decimal("20.0"),
    )
    # Объём блока A: 11+11+11+12=45, блока Б: 4+4+4+4+5=21, тренировка одна
    # (BlockLog.volume = сумма рабочих подходов + максимум).
    total_volume = 45 + 21

    body = await _get_analytics(session, telegram_id=user.telegram_id)

    assert body["has_data"] is True
    # Единственная тренировка внутри последних 7 дней, предыдущей недели
    # нет — volume_change_pct не определён (app.domain.reports._pct_change:
    # None, если предыдущий объём — 0).
    assert body["weekly"] == {
        "workout_count": 1, "total_volume": total_volume, "volume_change_pct": None,
        "equipment_changed_a": False, "equipment_changed_b": False,
    }
    assert body["equipment_progress_a"]["first_volume"] == 45
    assert body["equipment_progress_a"]["current_volume"] == 45
    assert body["equipment_progress_a"]["change_pct"] == 0.0
    assert body["equipment_progress_b"]["first_volume"] == 21
    assert body["equipment_progress_b"]["current_volume"] == 21
    assert body["total_volume"] == total_volume
    assert body["cycle_count"] == 1
    assert body["cycles"] == [
        {
            "workout_set_id": workout_set.id, "workout_count": 1,
            "total_volume": total_volume, "volume_change_pct": None,
        },
    ]
    # Блок Б на резине (BAND) — формула Эпли для неё не определена (issue #96).
    assert body["epley_progress"] is None


async def test_analytics_epley_progress_for_weight_block_b(session):
    user = await UserRepository(session).create(telegram_id=54004, username="epley")
    await UserRepository(session).update_profile(user.id, weight_kg=Decimal(70))
    baseline = await BaselineRepository(session).create(
        user_id=user.id, performed_at=datetime.now(UTC) - timedelta(days=10), reps=10,
    )
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    # (70 + 10) кг × (1 + 6/30) = 80 × 1.2 = 96.0; единственная тренировка
    # блока Б на отягощении — "прошлая"/"первая" совпадают с текущей (0%).
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC) - timedelta(days=3),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(), max_reps=6),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=Decimal("20.0"),
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=Decimal(10),
    )

    body = await _get_analytics(session, telegram_id=user.telegram_id)

    assert body["epley_progress"] == {
        "current_load_kg": 96.0, "change_pct_vs_previous": 0.0, "change_pct_vs_first": 0.0,
    }
