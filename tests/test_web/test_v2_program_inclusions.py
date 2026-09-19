"""POST /api/v2/program-inclusions (issue #165, волна 3) — snapshot +
инициализация progression_state для STEP-стратегии, числа посчитаны руками
по плану (см. "Стиль тестирования" в CLAUDE.md), не выведены из
тестируемого кода."""

from app.db.models import User
from app.db.models_program import Exercise, Program, ProgressionStrategyProfile
from app.domain.multi_program import MetricType, ProgramStructureType
from app.domain.progression_strategy import ProgressionStrategyType
from tests.test_web._v2_client import v2_get, v2_post


async def _make_step_program(session, *, category: str = "pullups_synth") -> Program:
    profile = ProgressionStrategyProfile(strategy_type=ProgressionStrategyType.STEP, name="Step test", config={})
    session.add(profile)
    await session.flush()

    program = Program(
        name="Синтетические подтягивания", goal="test", structure_type=ProgramStructureType.RECURRING,
        category=category, progression_strategy_id=profile.id,
        config={"block_a": {"base_target": 10, "work_sets": 3}, "block_b": {"base_target": 3}},
    )
    session.add(program)
    await session.flush()

    exercise_a = Exercise(
        name="Блок A", metric_type=MetricType.REPS, category=category, subcategory="block_a",
    )
    exercise_b = Exercise(
        name="Блок Б", metric_type=MetricType.REPS, category=category, subcategory="block_b",
    )
    session.add_all([exercise_a, exercise_b])
    await session.flush()
    return program


async def test_create_inclusion_for_unknown_telegram_id_is_404(session):
    response = await v2_post(
        session, telegram_id=60201, path="/api/v2/program-inclusions", payload={"program_id": 1},
    )
    assert response.status_code == 404


async def test_create_inclusion_for_unknown_program_id_is_404(session, user: User):
    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/program-inclusions", payload={"program_id": 999999},
    )
    assert response.status_code == 404


async def test_create_inclusion_starts_from_config_base_targets_with_no_override(session, user: User):
    program = await _make_step_program(session)

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/program-inclusions",
        payload={"program_id": program.id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["program_id"] == program.id
    assert body["program_name"] == "Синтетические подтягивания"
    assert body["is_active"] is True

    state = body["progression_state"]
    # Ручной расчёт по плану: без initial_target_a/b — старт с
    # config.block_a/b.base_target (10/3), объём/стрики с нуля, снаряд —
    # собственный вес (issue #165, план п.2).
    assert state["strategy_type"] == "step"
    assert state["block_a"] == {
        "target": 10, "volume": 0, "work_sets": 3, "work_sets_growth_reason": None,
        "weak_streak": 0, "stall_streak": 0, "equipment_type": "bodyweight",
        "equipment_value": None, "equipment_item_id": None, "needs_new_equipment": False,
    }
    assert state["block_b"] == {
        "target": 3, "volume": 0, "weak_streak": 0, "equipment_type": "bodyweight",
        "equipment_value": None, "equipment_item_id": None, "needs_new_equipment": False,
        "is_heavy_next": False, "heavy_equipment_value_next": None,
    }

    snapshot = body["snapshot"]
    assert snapshot["program_name"] == "Синтетические подтягивания"
    assert snapshot["progression_strategy_type"] == "step"
    assert {e["role"] for e in snapshot["exercises"]} == {"block_a", "block_b"}


async def test_create_inclusion_honors_explicit_initial_targets(session, user: User):
    program = await _make_step_program(session)

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/program-inclusions",
        payload={
            "program_id": program.id, "initial_target_a": 26, "initial_target_b": 8,
            "initial_volume_a": 40, "initial_volume_b": 24,
        },
    )

    assert response.status_code == 200
    state = response.json()["progression_state"]
    assert state["block_a"]["target"] == 26
    assert state["block_a"]["volume"] == 40
    assert state["block_b"]["target"] == 8
    assert state["block_b"]["volume"] == 24


async def test_create_inclusion_without_step_roles_leaves_progression_state_empty(session, user: User):
    """Программа без прогрессии (или без найденных block_a/block_b Exercise)
    — progression_state = {} (план issue #165, п.2, ветка "иначе")."""
    program = Program(
        name="Без ролей", goal="test", structure_type=ProgramStructureType.SINGLE_LESSON, config={},
    )
    session.add(program)
    await session.flush()

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/program-inclusions",
        payload={"program_id": program.id},
    )

    assert response.status_code == 200
    assert response.json()["progression_state"] == {}


async def test_create_inclusion_creates_training_plan_lazily(session, user: User):
    program = await _make_step_program(session)

    before = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")
    assert before.json()["plan"] is None

    await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/program-inclusions",
        payload={"program_id": program.id},
    )

    after = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")
    plan = after.json()["plan"]
    assert plan is not None
    assert len(plan["program_inclusions"]) == 1
    assert plan["program_inclusions"][0]["program_id"] == program.id


async def test_create_second_inclusion_reuses_same_training_plan(session, user: User):
    """Несколько ProgramInclusion могут сосуществовать в одном TrainingPlan
    (докстринг ProgramInclusion в models_program.py) — открытый пробел плана
    issue #165 (повторная инклюзия) здесь не проверяется, только то, что
    план не плодится по одному на инклюзию."""
    program_1 = await _make_step_program(session, category="pullups_synth_1")
    program_2 = await _make_step_program(session, category="pullups_synth_2")

    await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/program-inclusions",
        payload={"program_id": program_1.id},
    )
    await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/program-inclusions",
        payload={"program_id": program_2.id},
    )

    plan_response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")
    plan = plan_response.json()["plan"]
    assert len(plan["program_inclusions"]) == 2
