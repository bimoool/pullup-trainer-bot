from app.db.models_program import Exercise, Program, ProgramItem, ProgressionStrategyProfile
from app.db.repositories.programs import ProgramRepository
from app.domain.multi_program import MetricType, ProgramStructureType, WeekPhase
from app.domain.progression_strategy import ProgressionStrategyType


async def _make_program(session, *, name: str = "Синтетика", category: str | None = "synthetic") -> Program:
    program = Program(
        name=name, goal="test", structure_type=ProgramStructureType.RECURRING, category=category, config={},
    )
    session.add(program)
    await session.flush()
    return program


async def test_list_all_returns_all_programs(session):
    await _make_program(session, name="A")
    await _make_program(session, name="B")

    programs = await ProgramRepository(session).list_all()

    assert {p.name for p in programs} == {"A", "B"}


async def test_get_by_id_returns_none_for_unknown_id(session):
    assert await ProgramRepository(session).get_by_id(999999) is None


async def test_list_program_items_returns_items_for_program_only(session):
    program = await _make_program(session)
    other_program = await _make_program(session, name="Other")
    exercise = Exercise(name="Push-ups", metric_type=MetricType.REPS, category="synthetic")
    session.add(exercise)
    await session.flush()

    item = ProgramItem(
        program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=exercise.id, count_per_week=3, day_of_week=1,
    )
    other_item = ProgramItem(
        program_id=other_program.id, week_phase=WeekPhase.BASE, exercise_id=exercise.id, count_per_week=2,
    )
    session.add_all([item, other_item])
    await session.flush()

    items = await ProgramRepository(session).list_program_items(program.id)

    assert [i.id for i in items] == [item.id]


async def test_find_step_role_exercises_matches_by_category_and_subcategory(session):
    """Конвенция подтверждена Кириллом в issue #165: Exercise.category ==
    Program.category + subcategory in (block_a, block_b) — та же, что уже
    использует scripts/backfill_multi_program.py."""
    exercise_a = Exercise(name="Block A", metric_type=MetricType.REPS, category="pullups", subcategory="block_a")
    exercise_b = Exercise(name="Block B", metric_type=MetricType.REPS, category="pullups", subcategory="block_b")
    unrelated = Exercise(name="Other cat", metric_type=MetricType.REPS, category="other", subcategory="block_a")
    session.add_all([exercise_a, exercise_b, unrelated])
    await session.flush()

    roles = await ProgramRepository(session).find_step_role_exercises(category="pullups")

    assert roles == {"block_a": exercise_a, "block_b": exercise_b}


async def test_find_step_role_exercises_returns_empty_for_none_category(session):
    assert await ProgramRepository(session).find_step_role_exercises(category=None) == {}


async def test_get_strategy_profile_returns_none_for_unknown_id(session):
    assert await ProgramRepository(session).get_strategy_profile(999999) is None


async def test_get_strategy_profile_returns_saved_profile(session):
    profile = ProgressionStrategyProfile(strategy_type=ProgressionStrategyType.STEP, name="Step", config={})
    session.add(profile)
    await session.flush()

    fetched = await ProgramRepository(session).get_strategy_profile(profile.id)

    assert fetched is not None
    assert fetched.strategy_type == ProgressionStrategyType.STEP
