"""GET /api/workout/plan + POST /api/workout/submit — Этап 1 Mini App
(issue #36): форма ввода результатов тренировки, тонкая обвязка вокруг
тех же repositories/services/domain, что использует бот
(app/bot/handlers/workout.py). Сужение скоупа, согласованное в issue:
только "обычная" тренировка (needs_new_equipment=False для обоих блоков,
не разгрузочная) и gap_rollback — остальные случаи (too_early,
gap_retest_required, deload_due, equipment_setup_required, first_workout,
без подписки/онбординга) Mini App не обрабатывает формой, только сообщает
статус, тот же самый, что определил бы ветку в боте.

Главное, что эти тесты доказывают (issue #36, п.8 плана): POST
/api/workout/submit пишет тренировку ЧЕРЕЗ WorkoutLogService.record_workout
— тот же сервис и тот же каскад пересчёта прогрессии, что и бот, не
отдельная веб-копия. test_submit_uses_same_progression_as_direct_repository_call
сравнивает результат HTTP-запроса с прямым вызовом
WorkoutRepository.record_workout на идентичной истории — расхождение здесь
означало бы, что веб-слой действительно продублировал логику, а не
переиспользовал её."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from app.db.models import BlockType, User
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import ROLLBACK_REPS, EquipmentType
from app.domain.session import BlockLog
from app.services.subscription import SubscriptionService
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.main import app

BAND_VALUE = Decimal("15.0")


@dataclass
class _FakeWebAppUser:
    id: int
    first_name: str


@dataclass
class _FakeInitData:
    user: _FakeWebAppUser


def _override_dependencies(session, telegram_id: int) -> None:
    # Тот же приём, что tests/test_web/test_hello.py — реальная Telegram-
    # подпись проверяется отдельно (test_auth.py), здесь initData подменяется
    # через dependency_overrides.
    app.dependency_overrides[get_validated_init_data] = (
        lambda: _FakeInitData(user=_FakeWebAppUser(id=telegram_id, first_name="Тест"))
    )

    async def _override_session():
        yield session

    app.dependency_overrides[get_session] = _override_session


async def _get_plan(session, telegram_id: int) -> dict:
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/workout/plan")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    return response.json()


async def _post_submit(session, telegram_id: int, payload: dict) -> dict:
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/workout/submit", json=payload)
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    return response.json()


async def _make_returning_user(
    session, *, telegram_id: int, days_ago: int, block_a_reps: BlockLog | None = None,
) -> User:
    """Пользователь с ровно одной прошлой тренировкой days_ago дней назад —
    снаряд (BAND, значение ниже equipment_change_threshold обоих блоков)
    уже известен для обоих блоков, needs_new_equipment=False на следующей
    (см. app/db/repositories/workouts.py::_resolve_next_state)."""
    user = await UserRepository(session).create(telegram_id=telegram_id, username="tester")
    now = datetime.now(UTC)
    await SubscriptionService(session).start_trial(user.id, now=now)

    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=now, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=now - timedelta(days=days_ago),
        block_a_reps=block_a_reps or BlockLog(working_reps=(10, 10, 10), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    return user


async def _make_returning_user_with_weight_block_b(
    session, *, telegram_id: int, days_ago: int, weight_value: Decimal,
) -> User:
    """Как _make_returning_user, но блок B (сила) на отягощении, не резине
    — нужен для проверки правки "фактический вес" (issue #45, часть 2), она
    имеет смысл только для WEIGHT (см. app/web/routes.py::submit_workout)."""
    user = await UserRepository(session).create(telegram_id=telegram_id, username="tester")
    now = datetime.now(UTC)
    await SubscriptionService(session).start_trial(user.id, now=now)

    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=now, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=now - timedelta(days=days_ago),
        block_a_reps=BlockLog(working_reps=(10, 10, 10), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=weight_value,
    )
    return user


# --- GET /api/workout/plan — статусы -----------------------------------------------


async def test_plan_for_unknown_telegram_id_is_not_onboarded(session):
    body = await _get_plan(session, telegram_id=42001)
    assert body["status"] == "not_onboarded"


async def test_plan_without_subscription_is_no_access(session):
    user = await UserRepository(session).create(telegram_id=42002, username="nosub")
    body = await _get_plan(session, telegram_id=user.telegram_id)
    assert body["status"] == "no_access"


async def test_plan_without_history_is_first_workout(session):
    user = await UserRepository(session).create(telegram_id=42003, username="fresh")
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))
    body = await _get_plan(session, telegram_id=user.telegram_id)
    assert body["status"] == "first_workout"


async def test_plan_too_early_is_reported(session):
    user = await _make_returning_user(session, telegram_id=42004, days_ago=1)
    body = await _get_plan(session, telegram_id=user.telegram_id)
    assert body["status"] == "too_early"


async def test_plan_gap_retest_required_is_reported(session):
    user = await _make_returning_user(session, telegram_id=42005, days_ago=40)
    body = await _get_plan(session, telegram_id=user.telegram_id)
    assert body["status"] == "gap_retest_required"


async def test_plan_equipment_setup_required_is_reported(session):
    # (20, 20, 20) — каждый рабочий подход достиг equipment_change_threshold
    # блока на объём (20), см. test_equipment_threshold_hit_unlocks_equipment_changed
    # в tests/test_services/test_workout_log_service.py — тот же проверенный
    # приём, чтобы вызвать equipment_changed=True на прошлой тренировке.
    user = await _make_returning_user(
        session, telegram_id=42006, days_ago=5,
        block_a_reps=BlockLog(working_reps=(20, 20, 20), max_reps=21),
    )
    body = await _get_plan(session, telegram_id=user.telegram_id)
    assert body["status"] == "equipment_setup_required"


async def test_plan_ready_shows_target_and_equipment(session):
    user = await _make_returning_user(session, telegram_id=42007, days_ago=5)
    body = await _get_plan(session, telegram_id=user.telegram_id)

    assert body["status"] == "ready"
    assert body["is_gap_rollback"] is False
    assert body["work_sets_a"] == 3
    assert body["work_sets_b"] == 4
    assert body["equipment_a"]["type"] == "band"
    assert Decimal(body["equipment_a"]["value"]) == BAND_VALUE
    assert body["equipment_a"]["item_id"] is None
    assert body["equipment_a"]["label"] == "резина"
    assert body["workout_set_id"] is not None


async def test_plan_gap_rollback_overrides_target_a_by_rollback_reps(session):
    ready_user = await _make_returning_user(session, telegram_id=42008, days_ago=5)
    rollback_user = await _make_returning_user(session, telegram_id=42009, days_ago=25)

    ready_body = await _get_plan(session, telegram_id=ready_user.telegram_id)
    rollback_body = await _get_plan(session, telegram_id=rollback_user.telegram_id)

    assert ready_body["status"] == "ready"
    assert rollback_body["status"] == "ready"
    assert rollback_body["is_gap_rollback"] is True
    # Одна и та же прошлая тренировка в обоих случаях (_make_returning_user
    # с одинаковыми реальными числами) => одинаковый target_a_state.target
    # до отката — единственная разница должна быть ровно в ROLLBACK_REPS.
    assert rollback_body["target_a"] == ready_body["target_a"] - ROLLBACK_REPS
    assert rollback_body["target_b"] == ready_body["target_b"]


# --- POST /api/workout/submit -------------------------------------------------------


async def test_submit_for_unknown_telegram_id_reports_status_without_writing(session):
    payload = {
        "block_a_working_reps": [11, 11, 11], "block_a_max_reps": 12,
        "block_b_working_reps": [4, 4, 4, 4], "block_b_max_reps": 4,
        "comment": None, "confirm_anomalies": False,
    }
    body = await _post_submit(session, telegram_id=99999, payload=payload)
    assert body["status"] == "not_onboarded"


async def test_submit_uses_same_progression_as_direct_repository_call(session):
    """Доказательство "та же бизнес-логика, не копия" (issue #36, п.8
    плана): результат HTTP-запроса и результат прямого вызова
    WorkoutRepository.record_workout на идентичной истории должны
    совпасть по target_after/work_sets_after."""
    user_web = await _make_returning_user(session, telegram_id=42010, days_ago=5)
    user_direct = await _make_returning_user(session, telegram_id=42011, days_ago=5)

    payload = {
        "block_a_working_reps": [11, 11, 11], "block_a_max_reps": 12,
        "block_b_working_reps": [4, 4, 4, 4], "block_b_max_reps": 4,
        "comment": "с телефона", "confirm_anomalies": False,
    }
    body = await _post_submit(session, telegram_id=user_web.telegram_id, payload=payload)
    assert body["status"] == "ok"

    active_set = await WorkoutSetRepository(session).get_active_for_user(user_direct.id)
    direct_workout = await WorkoutRepository(session).record_workout(
        user_id=user_direct.id, workout_set_id=active_set.id, performed_at=datetime.now(UTC),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=4),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    direct_block_a = next(b for b in direct_workout.blocks if b.block_type == BlockType.A)
    direct_block_b = next(b for b in direct_workout.blocks if b.block_type == BlockType.B)

    assert body["target_a"] == direct_block_a.target_after
    assert body["target_b"] == direct_block_b.target_after

    web_history = await WorkoutRepository(session).list_for_user(user_web.id)
    assert len(web_history) == 2
    web_block_a = next(b for b in web_history[-1].blocks if b.block_type == BlockType.A)
    web_block_b = next(b for b in web_history[-1].blocks if b.block_type == BlockType.B)
    assert web_block_a.target_after == direct_block_a.target_after
    assert web_block_a.work_sets_after == direct_block_a.work_sets_after
    assert web_block_b.target_after == direct_block_b.target_after
    assert web_history[-1].comment == "с телефона"


async def test_submit_with_anomaly_requires_confirmation_and_does_not_write(session):
    user = await _make_returning_user(session, telegram_id=42012, days_ago=5)
    payload = {
        "block_a_working_reps": [60, 60, 60], "block_a_max_reps": 61,
        "block_b_working_reps": [4, 4, 4, 4], "block_b_max_reps": 4,
        "comment": None, "confirm_anomalies": False,
    }

    body = await _post_submit(session, telegram_id=user.telegram_id, payload=payload)

    assert body["status"] == "anomaly_confirm_required"
    assert body["anomalies_a"]["large_value"] == 61
    history = await WorkoutRepository(session).list_for_user(user.id)
    assert len(history) == 1  # только исходная тренировка из _make_returning_user

    payload["confirm_anomalies"] = True
    body = await _post_submit(session, telegram_id=user.telegram_id, payload=payload)

    assert body["status"] == "ok"
    history = await WorkoutRepository(session).list_for_user(user.id)
    assert len(history) == 2


# --- POST /api/workout/submit — фактический вес (issue #45, часть 2) ---------------


async def test_submit_applies_actual_weight_override_for_weight_block(session):
    """block_b_actual_weight переопределяет унаследованный из прогрессии
    вес блока B (WEIGHT) — тот же смысл, что "✏️ Изменить вес/резину" в
    боте (app/bot/handlers/workout.py::handle_change_block_equipment)."""
    user = await _make_returning_user_with_weight_block_b(
        session, telegram_id=42013, days_ago=5, weight_value=Decimal("10.0"),
    )
    plan = await _get_plan(session, telegram_id=user.telegram_id)
    assert plan["equipment_b"]["type"] == "weight"
    assert Decimal(plan["equipment_b"]["value"]) == Decimal("10.0")

    payload = {
        "block_a_working_reps": [11, 11, 11], "block_a_max_reps": 12,
        "block_b_working_reps": [4, 4, 4, 4], "block_b_max_reps": 4,
        "block_b_actual_weight": "12.5",
        "comment": None, "confirm_anomalies": False,
    }
    body = await _post_submit(session, telegram_id=user.telegram_id, payload=payload)

    assert body["status"] == "ok"
    assert Decimal(body["equipment_b"]["value"]) == Decimal("12.5")

    history = await WorkoutRepository(session).list_for_user(user.id)
    written_block_b = next(b for b in history[-1].blocks if b.block_type == BlockType.B)
    assert written_block_b.equipment_value == Decimal("12.5")


async def test_submit_ignores_actual_weight_override_for_non_weight_block(session):
    """block_a_actual_weight для блока A на резине (BAND) не должен
    ничего менять — правка веса имеет смысл только для WEIGHT, у резины
    "вес" не то же самое, что фиксированный груз (см. app/web/routes.py)."""
    user = await _make_returning_user(session, telegram_id=42014, days_ago=5)
    payload = {
        "block_a_working_reps": [11, 11, 11], "block_a_max_reps": 12,
        "block_a_actual_weight": "99",
        "block_b_working_reps": [4, 4, 4, 4], "block_b_max_reps": 4,
        "comment": None, "confirm_anomalies": False,
    }
    body = await _post_submit(session, telegram_id=user.telegram_id, payload=payload)

    assert body["status"] == "ok"
    assert Decimal(body["equipment_a"]["value"]) == BAND_VALUE
