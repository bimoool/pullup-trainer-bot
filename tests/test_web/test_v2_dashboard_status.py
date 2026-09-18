"""GET /api/v2/dashboard/status (issue #167, волна 4) — статус-логика Dashboard
поверх ProgramInclusion.progression_state, числа сверены с планом руками
(см. "Стиль тестирования" в CLAUDE.md), не выведены из тестируемого кода."""

from datetime import UTC, datetime, timedelta

from app.db.models import User
from app.db.models_program import Exercise, Program, ProgramInclusion, ProgressionStrategyProfile
from app.domain.constants import EquipmentType
from app.domain.multi_program import MetricType, ProgramStructureType
from app.domain.progression import recalculate_volume_block, rollback_target
from app.domain.progression_strategy import ProgressionStrategyType
from tests.test_web._v2_client import v2_get, v2_post

# Тот же ввод, что _record_session_days_ago ниже отправляет в POST
# /api/v2/sessions для блока A каждой синтетической тренировки — общая
# точка, откуда тесты ниже считают ОЖИДАЕМУЮ цель прямым вызовом домена
# (app.domain.progression.recalculate_volume_block), а не берут её из
# ответа тестируемого HTTP-эндпоинта (см. "Стиль тестирования" в CLAUDE.md).
_BLOCK_A_WORKING_REPS = (11, 11, 11)
_BLOCK_A_MAX_REPS = 12


async def _make_step_program(session, *, category: str = "pullups_dashboard") -> Program:
    profile = ProgressionStrategyProfile(strategy_type=ProgressionStrategyType.STEP, name="Step", config={})
    session.add(profile)
    await session.flush()
    program = Program(
        name="Синтетика дашборда", goal="test", structure_type=ProgramStructureType.RECURRING,
        category=category, progression_strategy_id=profile.id,
        config={"block_a": {"base_target": 10, "work_sets": 3}, "block_b": {"base_target": 3}},
    )
    session.add(program)
    await session.flush()
    session.add_all([
        Exercise(name="Блок A", metric_type=MetricType.REPS, category=category, subcategory="block_a"),
        Exercise(name="Блок Б", metric_type=MetricType.REPS, category=category, subcategory="block_b"),
    ])
    await session.flush()
    return program


async def _create_inclusion(session, telegram_id: int, program_id: int) -> dict:
    response = await v2_post(
        session, telegram_id=telegram_id, path="/api/v2/program-inclusions", payload={"program_id": program_id},
    )
    assert response.status_code == 200
    return response.json()


def _exercise_ids_by_role(inclusion: dict) -> dict[str, int]:
    return {e["role"]: e["exercise_id"] for e in inclusion["snapshot"]["exercises"]}


def _sets_block(exercise_id: int, working_reps: list[int], max_reps: int) -> dict:
    sets = [
        {"set_number": i + 1, "metric_type": "reps", "value": str(r), "unit": "reps"}
        for i, r in enumerate(working_reps)
    ]
    sets.append({
        "set_number": len(working_reps) + 1, "metric_type": "reps", "value": str(max_reps), "unit": "reps",
        "is_max_set": True,
    })
    return {"exercise_id": exercise_id, "sets": sets}


async def _record_session_days_ago(session, telegram_id: int, inclusion: dict, days_ago: int) -> None:
    """Пишет TrainingSession через тот же POST, что и реальный клиент, а не
    напрямую через репозиторий — оставаясь на пути, который проверяют
    остальные тесты этого модуля (issue #165)."""
    roles = _exercise_ids_by_role(inclusion)
    performed_at = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    response = await v2_post(
        session, telegram_id=telegram_id, path="/api/v2/sessions",
        payload={
            "source": "plan", "performed_at": performed_at, "program_inclusion_id": inclusion["id"],
            "blocks": [_sets_block(roles["block_a"], [11, 11, 11], 12), _sets_block(roles["block_b"], [4, 4, 4, 4], 4)],
        },
    )
    assert response.status_code == 200


async def test_dashboard_status_for_unknown_telegram_id_is_404(session):
    response = await v2_get(session, telegram_id=60501, path="/api/v2/dashboard/status")
    assert response.status_code == 404


async def test_dashboard_status_without_training_plan_is_not_migrated(session, user: User):
    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/dashboard/status")
    assert response.status_code == 200
    assert response.json()["status"] == "not_migrated"


async def test_dashboard_status_without_active_inclusion_is_not_migrated(session, user: User):
    program = await _make_step_program(session)
    inclusion = await _create_inclusion(session, user.telegram_id, program.id)

    # Деактивируем ту же единственную инклюзию напрямую через ORM — у
    # ProgramInclusionService на этой волне нет эндпоинта "остановить курс"
    # (вне охвата issue #165/#167), это синтетическая подготовка данных.
    row = await session.get(ProgramInclusion, inclusion["id"])
    row.is_active = False
    await session.flush()

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/dashboard/status")
    assert response.status_code == 200
    assert response.json()["status"] == "not_migrated"


async def test_dashboard_status_with_non_step_inclusion_is_not_migrated(session, user: User):
    program = Program(
        name="Без стратегии", goal="test", structure_type=ProgramStructureType.SINGLE_LESSON,
        category="no_strategy_dashboard", config={},
    )
    session.add(program)
    await session.flush()
    session.add(Exercise(name="Одиночное", metric_type=MetricType.REPS, category="no_strategy_dashboard"))
    await session.flush()
    inclusion = await _create_inclusion(session, user.telegram_id, program.id)
    assert inclusion["progression_state"] == {}

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/dashboard/status")
    assert response.status_code == 200
    assert response.json()["status"] == "not_migrated"


async def test_dashboard_status_with_two_active_inclusions_is_ambiguous(session, user: User):
    program_1 = await _make_step_program(session, category="pullups_dashboard_1")
    program_2 = await _make_step_program(session, category="pullups_dashboard_2")
    await _create_inclusion(session, user.telegram_id, program_1.id)
    await _create_inclusion(session, user.telegram_id, program_2.id)

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/dashboard/status")
    assert response.status_code == 200
    assert response.json()["status"] == "multiple_active_inclusions"


async def test_dashboard_status_ready_before_any_session_shows_config_base_targets(session, user: User):
    """Без единой TrainingSession читать готовность не от чего сравнивать —
    статус сразу "ready" с начальными значениями progression_state (те же
    числа, что test_create_inclusion_starts_from_config_base_targets_with_no_override
    в tests/test_web/test_v2_program_inclusions.py)."""
    program = await _make_step_program(session)
    await _create_inclusion(session, user.telegram_id, program.id)

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/dashboard/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["program_name"] == "Синтетика дашборда"
    assert body["is_gap_rollback"] is False
    assert body["block_a"] == {
        "target": 10, "work_sets": 3,
        "equipment": {
            "type": "bodyweight", "value": None, "item_id": None,
            "label": "собственный вес", "needs_new_equipment": False,
        },
    }
    assert body["block_b"] == {
        "target": 3, "work_sets": 4,
        "equipment": {
            "type": "bodyweight", "value": None, "item_id": None,
            "label": "собственный вес", "needs_new_equipment": False,
        },
    }


async def test_dashboard_status_too_early_right_after_a_session(session, user: User):
    program = await _make_step_program(session)
    inclusion = await _create_inclusion(session, user.telegram_id, program.id)
    await _record_session_days_ago(session, user.telegram_id, inclusion, days_ago=0)

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/dashboard/status")
    assert response.status_code == 200
    assert response.json()["status"] == "too_early"


async def test_dashboard_status_gap_retest_required_after_long_break(session, user: User):
    program = await _make_step_program(session)
    inclusion = await _create_inclusion(session, user.telegram_id, program.id)
    # GAP_RETEST_DAYS = 35 (app/domain/constants.py) - 40 дней однозначно за порогом.
    await _record_session_days_ago(session, user.telegram_id, inclusion, days_ago=40)

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/dashboard/status")
    assert response.status_code == 200
    assert response.json()["status"] == "gap_retest_required"


def _expected_target_a_after_one_session() -> int:
    """Прямой вызов того же домена, что StepProgressionStrategy.apply()
    делегирует изнутри (app/domain/progression_strategy.py) - независимое
    вычисление ожидаемой цели после ровно одной тренировки блока A с нуля
    (target=10, work_sets=3, volume=0 -> _BLOCK_A_WORKING_REPS/_MAX_REPS)."""
    result = recalculate_volume_block(
        10, 3, _BLOCK_A_WORKING_REPS, _BLOCK_A_MAX_REPS,
        sum(_BLOCK_A_WORKING_REPS) + _BLOCK_A_MAX_REPS, 0, EquipmentType.BODYWEIGHT,
        consecutive_weak_before=0, consecutive_stall_before=0,
    )
    return result.new_target


async def test_dashboard_status_gap_rollback_reduces_target_a(session, user: User):
    """GAP_ROLLBACK_DAYS=21..GAP_RETEST_DAYS=35 (app/domain/constants.py) -
    25 дней внутри окна. Dashboard откатывает АКТУАЛЬНУЮ (уже пересчитанную
    прошлой тренировкой) цель, не стартовую константу 10 - тот же приём, что
    app/web/routes.py::_resolve_plan_context делает для старой схемы."""
    program = await _make_step_program(session)
    inclusion = await _create_inclusion(session, user.telegram_id, program.id)
    await _record_session_days_ago(session, user.telegram_id, inclusion, days_ago=25)

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/dashboard/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["is_gap_rollback"] is True
    assert body["block_a"]["target"] == rollback_target(_expected_target_a_after_one_session())


async def test_dashboard_status_ready_reflects_last_recorded_progression(session, user: User):
    program = await _make_step_program(session)
    inclusion = await _create_inclusion(session, user.telegram_id, program.id)
    # MIN_REST_DAYS=2, GAP_ROLLBACK_DAYS=21 (app/domain/constants.py) - 3 дня
    # внутри READY-окна, не too_early и не gap_rollback.
    await _record_session_days_ago(session, user.telegram_id, inclusion, days_ago=3)

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/dashboard/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["is_gap_rollback"] is False
    # Dashboard показывает АКТУАЛЬНОЕ состояние после записанной тренировки,
    # не замороженную стартовую цель 10 (та же формула, что и в тесте выше,
    # без отката - здесь не gap_rollback).
    assert body["block_a"]["target"] == _expected_target_a_after_one_session()
