from app.db.models import User
from app.db.models_program import Exercise, Program, ProgramItem
from app.db.repositories.training_plans import TrainingPlanRepository
from app.domain.multi_program import MetricType, ProgramStructureType, WeekPhase


async def _make_program_with_items(session) -> tuple[Program, list[ProgramItem]]:
    program = Program(
        name="Синтетика с матрицей", goal="test", structure_type=ProgramStructureType.RECURRING,
        category="synthetic", config={},
    )
    session.add(program)
    await session.flush()

    exercise = Exercise(name="Push-ups", metric_type=MetricType.REPS, category="synthetic")
    session.add(exercise)
    await session.flush()

    items = [
        ProgramItem(
            program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=exercise.id,
            count_per_week=3, day_of_week=1,
        ),
        ProgramItem(
            program_id=program.id, week_phase=WeekPhase.PEAK, exercise_id=exercise.id,
            count_per_week=2, day_of_week=None,
        ),
    ]
    session.add_all(items)
    await session.flush()
    return program, items


async def test_get_or_create_for_user_creates_exactly_once(session, user: User):
    repo = TrainingPlanRepository(session)

    first = await repo.get_or_create_for_user(user.id)
    second = await repo.get_or_create_for_user(user.id)

    assert first.id == second.id


async def test_get_for_user_returns_none_before_creation(session, user: User):
    assert await TrainingPlanRepository(session).get_for_user(user.id) is None


async def test_create_inclusion_and_list_inclusions(session, user: User):
    program, _ = await _make_program_with_items(session)
    repo = TrainingPlanRepository(session)
    plan = await repo.get_or_create_for_user(user.id)

    inclusion = await repo.create_inclusion(
        training_plan_id=plan.id, program_id=program.id,
        snapshot={"program_name": program.name}, progression_state={},
    )

    inclusions = await repo.list_inclusions(plan.id)
    assert [i.id for i in inclusions] == [inclusion.id]
    assert inclusions[0].is_active is True


async def test_get_inclusion_for_user_returns_none_for_foreign_inclusion(session, user: User):
    other_user = User(telegram_id=99999999, username="other")
    session.add(other_user)
    await session.flush()

    program, _ = await _make_program_with_items(session)
    repo = TrainingPlanRepository(session)
    other_plan = await repo.get_or_create_for_user(other_user.id)
    inclusion = await repo.create_inclusion(
        training_plan_id=other_plan.id, program_id=program.id, snapshot={}, progression_state={},
    )

    assert await repo.get_inclusion_for_user(inclusion.id, user.id) is None
    assert await repo.get_inclusion_for_user(inclusion.id, other_user.id) is not None


async def test_update_progression_state_persists_new_dict(session, user: User):
    program, _ = await _make_program_with_items(session)
    repo = TrainingPlanRepository(session)
    plan = await repo.get_or_create_for_user(user.id)
    inclusion = await repo.create_inclusion(
        training_plan_id=plan.id, program_id=program.id, snapshot={}, progression_state={"block_a": {"target": 10}},
    )

    await repo.update_progression_state(inclusion.id, {"block_a": {"target": 11}})

    reloaded = await repo.get_inclusion_by_id(inclusion.id)
    assert reloaded.progression_state == {"block_a": {"target": 11}}


async def test_bulk_create_plan_items_from_program_items_copies_rows(session, user: User):
    program, program_items = await _make_program_with_items(session)
    repo = TrainingPlanRepository(session)
    plan = await repo.get_or_create_for_user(user.id)
    inclusion = await repo.create_inclusion(
        training_plan_id=plan.id, program_id=program.id, snapshot={}, progression_state={},
    )

    created = await repo.bulk_create_plan_items_from_program_items(
        training_plan_id=plan.id, program_inclusion_id=inclusion.id, program_items=program_items,
    )

    assert len(created) == 2
    plan_items = await repo.list_plan_items(plan.id)
    assert {(i.count_per_week, i.day_of_week, i.week_phase) for i in plan_items} == {
        (3, 1, WeekPhase.BASE), (2, None, WeekPhase.PEAK),
    }
    assert all(i.program_inclusion_id == inclusion.id for i in plan_items)


async def test_bulk_create_plan_items_skips_complex_only_program_items(session, user: User):
    """PlanItem.exercise_id — NOT NULL в схеме волны 1 (models_program.py),
    но ProgramItem.exercise_id допускает None (строка на Complex без
    отдельного Exercise) — копирование такой строки пропускается, не падает
    IntegrityError (известный пробел схемы, см. app/db/repositories/
    training_plans.py::bulk_create_plan_items_from_program_items)."""
    program = Program(
        name="Complex-only", goal="test", structure_type=ProgramStructureType.RECURRING, config={},
    )
    session.add(program)
    await session.flush()
    complex_only_item = ProgramItem(
        program_id=program.id, week_phase=WeekPhase.BASE, exercise_id=None, complex_id=None, count_per_week=1,
    )
    session.add(complex_only_item)
    await session.flush()

    repo = TrainingPlanRepository(session)
    plan = await repo.get_or_create_for_user(user.id)
    inclusion = await repo.create_inclusion(
        training_plan_id=plan.id, program_id=program.id, snapshot={}, progression_state={},
    )

    created = await repo.bulk_create_plan_items_from_program_items(
        training_plan_id=plan.id, program_inclusion_id=inclusion.id, program_items=[complex_only_item],
    )

    assert created == []


async def test_create_plan_item_manual_entry_has_no_program_inclusion(session, user: User):
    exercise = Exercise(name="Manual", metric_type=MetricType.REPS, category="synthetic")
    session.add(exercise)
    await session.flush()
    repo = TrainingPlanRepository(session)
    plan = await repo.get_or_create_for_user(user.id)

    item = await repo.create_plan_item(
        training_plan_id=plan.id, exercise_id=exercise.id, complex_id=None,
        count_per_week=1, day_of_week=None, week_phase=None, program_inclusion_id=None,
    )

    assert item.program_inclusion_id is None
    items = await repo.list_plan_items(plan.id, program_inclusion_id=None)
    assert [i.id for i in items] == [item.id]


async def test_list_plan_items_filters_by_program_inclusion_id(session, user: User):
    program, program_items = await _make_program_with_items(session)
    repo = TrainingPlanRepository(session)
    plan = await repo.get_or_create_for_user(user.id)
    inclusion = await repo.create_inclusion(
        training_plan_id=plan.id, program_id=program.id, snapshot={}, progression_state={},
    )
    await repo.bulk_create_plan_items_from_program_items(
        training_plan_id=plan.id, program_inclusion_id=inclusion.id, program_items=program_items,
    )
    manual_item = await repo.create_plan_item(
        training_plan_id=plan.id, exercise_id=program_items[0].exercise_id, complex_id=None,
        count_per_week=1, day_of_week=None, week_phase=None, program_inclusion_id=None,
    )

    filtered = await repo.list_plan_items(plan.id, program_inclusion_id=inclusion.id)
    assert manual_item.id not in [i.id for i in filtered]
    assert len(filtered) == 2

    all_items = await repo.list_plan_items(plan.id)
    assert len(all_items) == 3
