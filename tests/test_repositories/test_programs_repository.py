from app.db.models_program import (
    Complex,
    ComplexItem,
    Exercise,
    Program,
    ProgramItem,
    ProgressionStrategyProfile,
)
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


# --- Phase A1 (issue #214, Worker B) — Complex/ComplexItem protocol tests ---


async def test_create_complex_item_with_protocol_saves_and_reads_correctly(session):
    """ComplexItem.protocol — произвольный JSON сохраняется и читается без потерь."""
    exercise = Exercise(name="Intervals", metric_type=MetricType.TIME, category="cardio")
    session.add(exercise)
    await session.flush()

    complex = await ProgramRepository(session).create_complex(name="HIIT Workout")
    protocol_data = {"type": "interval", "work": 30, "rest": 15, "rounds": 8}
    await ProgramRepository(session).create_complex_item(
        complex_id=complex.id,
        exercise_id=exercise.id,
        order_index=0,
        sets=1,
        protocol=protocol_data,
    )
    await session.commit()

    # Re-read from DB
    fetched_items = await ProgramRepository(session).list_complex_items(complex.id)
    assert len(fetched_items) == 1
    assert fetched_items[0].protocol == protocol_data


async def test_legacy_complex_item_without_protocol_reads_as_null(session):
    """Существующий ComplexItem без protocol (созданный до миграции) читается корректно."""
    exercise = Exercise(name="Push-ups", metric_type=MetricType.REPS, category="strength")
    complex = Complex(name="Legacy Complex")
    session.add_all([exercise, complex])
    await session.flush()

    # Создать ComplexItem напрямую (минуя create_complex_item), не проставляя protocol
    item = ComplexItem(
        complex_id=complex.id,
        exercise_id=exercise.id,
        order_index=0,
        sets=3,
        target_value=10,
        target_unit="reps",
        rest_seconds=60,
        # protocol явно НЕ указан — остаётся NULL
    )
    session.add(item)
    await session.commit()

    # Re-read from DB
    fetched_items = await ProgramRepository(session).list_complex_items(complex.id)
    assert len(fetched_items) == 1
    assert fetched_items[0].protocol is None
    # Legacy поля должны остаться
    assert fetched_items[0].sets == 3
    assert fetched_items[0].target_value == 10
    assert fetched_items[0].rest_seconds == 60


async def test_create_complex_defaults_to_system_source_type(session):
    """Complex.source_type по умолчанию 'system' при создании без явного указания."""
    complex = await ProgramRepository(session).create_complex(name="Catalog Workout")
    await session.commit()

    fetched = await ProgramRepository(session).get_complex(complex.id)
    assert fetched is not None
    assert fetched.source_type == "system"
    assert fetched.owner_user_id is None


async def test_create_complex_with_user_source_and_owner(session):
    """Complex с source_type='user' + owner_user_id сохраняется и читается корректно."""
    # Создать фиктивного пользователя для FK
    from app.db.models import User
    user = User(telegram_id=12345, username="testuser")
    session.add(user)
    await session.flush()

    complex = await ProgramRepository(session).create_complex(
        name="My Custom Workout",
        source_type="user",
        owner_user_id=user.id,
    )
    await session.commit()

    fetched = await ProgramRepository(session).get_complex(complex.id)
    assert fetched is not None
    assert fetched.source_type == "user"
    assert fetched.owner_user_id == user.id
