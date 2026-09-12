"""GET /api/elective/plan + POST /api/elective/submit (issue #94) — тот же
путь, что handle_electives_start/_finalize_elective бота
(app/bot/handlers/electives.py): недельный лимит (ELECTIVE_MAX_PER_WEEK) и
ротация без повтора (available_elective_types) определяют доступность
формы, не статус готовности к обычной тренировке — факультатив доступен в
любой день, is_rest_day только меняет проактивный текст."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.elective_workouts import ElectiveWorkoutRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.constants import MIN_REST_DAYS, EquipmentType
from app.domain.electives import ElectiveType
from app.domain.session import BlockLog
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


async def _get_elective_plan(telegram_id: int, session) -> dict:
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/elective/plan")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    return response.json()


async def _post_elective_submit_raw(telegram_id: int, session, payload: dict):
    _override_dependencies(session, telegram_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/elective/submit", json=payload)
    finally:
        app.dependency_overrides.clear()


async def _post_elective_submit(telegram_id: int, session, payload: dict) -> dict:
    response = await _post_elective_submit_raw(telegram_id, session, payload)
    assert response.status_code == 200
    return response.json()


async def _make_history(session, *, telegram_id: int, performed_at: datetime) -> int:
    user = await UserRepository(session).create(telegram_id=telegram_id, username="tester")
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=performed_at, reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=performed_at,
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.WEIGHT, block_a_equipment_value=Decimal("20.0"),
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=Decimal("20.0"),
    )
    return user.id


async def test_plan_not_onboarded(session):
    result = await _get_elective_plan(999, session)
    assert result["status"] == "not_onboarded"


async def test_plan_needs_first_workout_without_history(session):
    user = await UserRepository(session).create(telegram_id=555, username="fresh")
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))

    result = await _get_elective_plan(555, session)
    assert result["status"] == "needs_first_workout"


async def test_plan_ready_even_without_active_subscription(session):
    # handle_electives_start бота не проверяет подписку (факультатив не за
    # паивеллом) — GET /api/elective/plan должен вести себя так же, не
    # заводить новый гейт, которого нет в боте.
    user = await UserRepository(session).create(telegram_id=777, username="broke")
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=datetime.now(UTC), reps=10)
    workout_set = await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=datetime.now(UTC),
        block_a_reps=BlockLog(working_reps=(11, 11, 11), max_reps=12),
        block_b_reps=BlockLog(working_reps=(4, 4, 4, 4), max_reps=5),
        block_a_equipment_type=EquipmentType.WEIGHT, block_a_equipment_value=Decimal("20.0"),
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=Decimal("20.0"),
    )

    result = await _get_elective_plan(777, session)
    assert result["status"] == "ready"


async def test_plan_ready_lists_all_four_when_none_done_and_marks_rest_day(session):
    telegram_id = 1
    # Тренировка "только что" — MIN_REST_DAYS ещё не прошло, TOO_EARLY.
    await _make_history(session, telegram_id=telegram_id, performed_at=datetime.now(UTC))

    result = await _get_elective_plan(telegram_id, session)
    assert result["status"] == "ready"
    assert result["is_rest_day"] is True
    assert result["ready_at"] is not None
    assert result["hours_left"] is not None
    assert result["elective_allowed"] is True
    assert result["elective_limit"] == 2
    assert result["entries_this_week"] == 0
    assert {t["value"] for t in result["available_types"]} == {e.value for e in ElectiveType}
    assert result["equipment_label"] is not None

    volume_target = next(t for t in result["available_types"] if t["value"] == "volume_target")
    assert volume_target["input_kind"] == "total"
    assert volume_target["volume_goal"] == volume_target["volume_goal"]  # заполнено (не None)
    assert volume_target["volume_goal"] is not None

    max_reps_ladder = next(t for t in result["available_types"] if t["value"] == "max_reps_ladder")
    assert max_reps_ladder["input_kind"] == "sequence"
    assert max_reps_ladder["min_count"] == 4
    assert max_reps_ladder["max_count"] == 4


async def test_plan_is_not_rest_day_when_enough_days_passed(session):
    telegram_id = 2
    await _make_history(
        session, telegram_id=telegram_id, performed_at=datetime.now(UTC) - timedelta(days=MIN_REST_DAYS + 1),
    )

    result = await _get_elective_plan(telegram_id, session)
    assert result["status"] == "ready"
    assert result["is_rest_day"] is False
    assert result["ready_at"] is None
    assert result["hours_left"] is None


async def test_plan_admin_never_marked_as_rest_day(session, monkeypatch):
    telegram_id = 3
    monkeypatch.setattr(settings, "admin_ids", str(telegram_id))
    await _make_history(session, telegram_id=telegram_id, performed_at=datetime.now(UTC))

    result = await _get_elective_plan(telegram_id, session)
    assert result["is_rest_day"] is False


async def test_plan_excludes_type_already_done_in_current_cycle(session):
    telegram_id = 4
    user_id = await _make_history(session, telegram_id=telegram_id, performed_at=datetime.now(UTC))
    await ElectiveWorkoutRepository(session).create(
        user_id=user_id, elective_type=ElectiveType.MAX_REPS_LADDER,
        performed_at=datetime.now(UTC) - timedelta(days=10),
        total_reps=30, reps_sequence=[10, 8, 7, 5], equipment_type=EquipmentType.BODYWEIGHT,
    )

    result = await _get_elective_plan(telegram_id, session)
    values = {t["value"] for t in result["available_types"]}
    assert "max_reps_ladder" not in values
    assert len(values) == 3


async def test_plan_reports_limit_reached_explicitly_with_empty_types(session):
    telegram_id = 5
    user_id = await _make_history(session, telegram_id=telegram_id, performed_at=datetime.now(UTC))
    # ELECTIVE_MAX_PER_WEEK == 2 (issue #94) — обе уже использованы в окне.
    await ElectiveWorkoutRepository(session).create(
        user_id=user_id, elective_type=ElectiveType.W_LADDER, performed_at=datetime.now(UTC),
        total_reps=20, reps_sequence=[5, 4, 3], equipment_type=EquipmentType.BODYWEIGHT,
    )
    await ElectiveWorkoutRepository(session).create(
        user_id=user_id, elective_type=ElectiveType.THREE_MINUTES, performed_at=datetime.now(UTC),
        total_reps=30, reps_sequence=[8, 7, 6, 5, 4], equipment_type=EquipmentType.BODYWEIGHT,
    )

    result = await _get_elective_plan(telegram_id, session)
    assert result["status"] == "ready"
    assert result["elective_allowed"] is False
    assert result["entries_this_week"] == 2
    assert result["available_types"] == []


async def test_submit_records_full_sequence_and_recomputes_sum_not_trusting_client(session):
    telegram_id = 6
    user_id = await _make_history(session, telegram_id=telegram_id, performed_at=datetime.now(UTC))

    result = await _post_elective_submit(
        telegram_id, session,
        {
            "elective_type": "max_reps_ladder",
            "reps_sequence": [12, 10, 8, 6],
            # Заведомо неверная сумма — сервер обязан пересчитать сам, не
            # доверять клиенту (тот же принцип, что и у остальных Submit).
            "total_reps": 999,
        },
    )
    assert result["status"] == "ok"
    assert result["result_text"] == "12, 10, 8, 6 (всего 36)"

    [elective] = await ElectiveWorkoutRepository(session).list_for_user(user_id)
    assert elective.elective_type == ElectiveType.MAX_REPS_LADDER
    assert elective.reps_sequence == [12, 10, 8, 6]
    assert elective.total_reps == 36
    # Снаряд — унаследован из блока на объём (WEIGHT 20кг в _make_history),
    # не выбирается отдельно, тот же принцип, что и у бота.
    assert elective.equipment_type == EquipmentType.WEIGHT
    assert elective.equipment_value == Decimal("20.00")


async def test_submit_rejects_wrong_sequence_length(session):
    telegram_id = 7
    await _make_history(session, telegram_id=telegram_id, performed_at=datetime.now(UTC))

    response = await _post_elective_submit_raw(
        telegram_id, session,
        {"elective_type": "max_reps_ladder", "reps_sequence": [12, 10, 8], "total_reps": 30},
    )
    assert response.status_code == 400


async def test_submit_volume_target_records_total_only_no_sequence(session):
    telegram_id = 8
    user_id = await _make_history(session, telegram_id=telegram_id, performed_at=datetime.now(UTC))

    result = await _post_elective_submit(
        telegram_id, session, {"elective_type": "volume_target", "total_reps": 52},
    )
    assert result["status"] == "ok"

    [elective] = await ElectiveWorkoutRepository(session).list_for_user(user_id)
    assert elective.reps_sequence is None
    assert elective.total_reps == 52


async def test_submit_volume_target_rejects_non_positive_total(session):
    telegram_id = 9
    await _make_history(session, telegram_id=telegram_id, performed_at=datetime.now(UTC))

    response = await _post_elective_submit_raw(
        telegram_id, session, {"elective_type": "volume_target", "total_reps": 0},
    )
    assert response.status_code == 400


async def test_submit_returns_limit_reached_status_without_writing(session):
    telegram_id = 10
    user_id = await _make_history(session, telegram_id=telegram_id, performed_at=datetime.now(UTC))
    await ElectiveWorkoutRepository(session).create(
        user_id=user_id, elective_type=ElectiveType.W_LADDER, performed_at=datetime.now(UTC),
        total_reps=20, reps_sequence=[5, 4, 3], equipment_type=EquipmentType.BODYWEIGHT,
    )
    await ElectiveWorkoutRepository(session).create(
        user_id=user_id, elective_type=ElectiveType.THREE_MINUTES, performed_at=datetime.now(UTC),
        total_reps=30, reps_sequence=[8, 7, 6, 5, 4], equipment_type=EquipmentType.BODYWEIGHT,
    )

    result = await _post_elective_submit(
        telegram_id, session, {"elective_type": "volume_target", "total_reps": 52},
    )
    assert result["status"] == "limit_reached"
    history = await ElectiveWorkoutRepository(session).list_for_user(user_id)
    assert len(history) == 2  # не выросло — новая запись не создана


async def test_submit_rejects_invalid_elective_type(session):
    telegram_id = 11
    await _make_history(session, telegram_id=telegram_id, performed_at=datetime.now(UTC))

    response = await _post_elective_submit_raw(
        telegram_id, session, {"elective_type": "not_a_real_type", "total_reps": 10},
    )
    assert response.status_code == 400


async def test_submit_needs_first_workout_without_history(session):
    user = await UserRepository(session).create(telegram_id=12, username="fresh2")
    await SubscriptionService(session).start_trial(user.id, now=datetime.now(UTC))

    result = await _post_elective_submit(
        12, session, {"elective_type": "volume_target", "total_reps": 10},
    )
    assert result["status"] == "needs_first_workout"
