import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, text

from app.db.models import EquipmentType, User
from app.db.models_program import (
    Exercise,
    Program,
    ProgramInclusion,
    SessionBlock,
    SetLog,
    TrainingPlan,
    TrainingSession,
)
from app.db.repositories.baselines import BaselineRepository
from app.db.repositories.elective_workouts import ElectiveWorkoutRepository
from app.db.repositories.equipment_items import EquipmentItemRepository
from app.db.repositories.users import UserRepository
from app.db.repositories.workout_sets import WorkoutSetRepository
from app.db.repositories.workouts import WorkoutRepository
from app.domain.electives import ElectiveType
from app.domain.multi_program import SessionSource
from app.domain.progression import initial_volume_target, suggest_starting_equipment
from app.domain.session import BlockLog
from scripts.backfill_multi_program import backfill_all, seed_catalog

NOW = datetime(2026, 9, 18, tzinfo=UTC)
BAND_VALUE = Decimal("18.0")


async def _onboard(session, user: User) -> None:
    await UserRepository(session).complete_onboarding(user.id, NOW)


async def _make_workout_set(session, user: User):
    baseline = await BaselineRepository(session).create(user_id=user.id, performed_at=NOW - timedelta(days=60), reps=8)
    return await WorkoutSetRepository(session).create(user_id=user.id, started_from_baseline_id=baseline.id)


async def test_not_onboarded_user_is_never_migrated(session, user: User):
    report = await backfill_all(session, now=NOW)

    assert report.users_onboarded == 0
    assert (await session.execute(select(TrainingPlan))).scalars().all() == []


async def test_onboarded_zero_workouts_gets_default_progression_state(session, user: User):
    await _onboard(session, user)

    report = await backfill_all(session, now=NOW)

    assert report.users_onboarded == 1
    assert report.users_migrated_this_run == 1
    plan = (await session.execute(select(TrainingPlan).where(TrainingPlan.user_id == user.id))).scalar_one()
    inclusion = (
        await session.execute(select(ProgramInclusion).where(ProgramInclusion.training_plan_id == plan.id))
    ).scalar_one()
    state = inclusion.progression_state
    assert state["block_a"] == {
        "target": 10, "volume": 0, "work_sets": 3, "work_sets_growth_reason": None,
        "weak_streak": 0, "stall_streak": 0, "equipment_type": "band", "equipment_value": None,
        "equipment_item_id": None, "needs_new_equipment": True,
    }
    assert state["block_b"] == {
        "target": 3, "volume": 0, "weak_streak": 0, "equipment_type": "band", "equipment_value": None,
        "equipment_item_id": None, "needs_new_equipment": True, "is_heavy_next": False,
        "heavy_equipment_value_next": None,
    }
    assert (await session.execute(select(TrainingSession).where(TrainingSession.user_id == user.id))).scalars().all() == []


async def test_zero_workouts_with_baseline_matches_first_workout_equipment_choice(session, user: User):
    """Реальный баг issue #172: свежий онбординг, замер 12 повторений, ни
    одной тренировки — Dashboard (progression_state) должен показывать тот
    же стартовый снаряд/цель, что и старый экран «Тренировка» для первой
    тренировки (_resolve_plan_context в app/web/routes.py:
    suggest_starting_equipment/initial_volume_target по замеру), а не
    заглушку resolve_next_targets (BAND, плоская base_target), которая для
    пустой истории baseline вообще не знает. Числа взяты из реального
    репорта в issue (замер 12 -> цель блока A 9, блок A на собственном
    весе, блок Б на отягощении), сверены и с прямым вызовом тех же
    доменных функций, что использует старая схема (см. CLAUDE.md "Стиль
    тестирования" — не цифра, посчитанная руками наугад, а то же
    вычисление, что и в проде)."""
    await _onboard(session, user)
    await BaselineRepository(session).create(user_id=user.id, performed_at=NOW - timedelta(days=1), reps=12)
    expected_equipment_a, expected_equipment_b = suggest_starting_equipment(12)
    expected_target_a = initial_volume_target(12)
    assert (expected_target_a, expected_equipment_a, expected_equipment_b) == (
        9, EquipmentType.BODYWEIGHT, EquipmentType.WEIGHT,
    )  # ручной расчёт по плану issue, проверка предпосылки теста

    await backfill_all(session, now=NOW)

    plan = (await session.execute(select(TrainingPlan).where(TrainingPlan.user_id == user.id))).scalar_one()
    inclusion = (
        await session.execute(select(ProgramInclusion).where(ProgramInclusion.training_plan_id == plan.id))
    ).scalar_one()
    state = inclusion.progression_state
    assert state["block_a"]["target"] == 9
    assert state["block_a"]["equipment_type"] == expected_equipment_a.value
    assert state["block_a"]["equipment_value"] is None
    assert state["block_a"]["needs_new_equipment"] is True
    assert state["block_b"]["target"] == 3
    assert state["block_b"]["equipment_type"] == expected_equipment_b.value
    assert state["block_b"]["equipment_value"] is None
    assert state["block_b"]["needs_new_equipment"] is True


async def test_band_user_progression_state_matches_equipment(session, user: User):
    await _onboard(session, user)
    band = await EquipmentItemRepository(session).create(user_id=user.id, name="Красная", resistance_kg=BAND_VALUE)
    workout_set = await _make_workout_set(session, user)
    workouts = WorkoutRepository(session)
    for day in (10, 5):
        await workouts.record_workout(
            user_id=user.id, workout_set_id=workout_set.id, performed_at=NOW - timedelta(days=day),
            block_a_reps=BlockLog(working_reps=(10, 10, 9), max_reps=11),
            block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
            block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
            block_a_equipment_item_id=band.id,
            block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
            block_b_equipment_item_id=band.id,
        )

    await backfill_all(session, now=NOW)

    plan = (await session.execute(select(TrainingPlan).where(TrainingPlan.user_id == user.id))).scalar_one()
    inclusion = (
        await session.execute(select(ProgramInclusion).where(ProgramInclusion.training_plan_id == plan.id))
    ).scalar_one()
    assert inclusion.progression_state["block_a"]["equipment_type"] == "band"
    assert inclusion.progression_state["block_a"]["equipment_item_id"] == band.id
    assert inclusion.progression_state["block_a"]["needs_new_equipment"] is False

    sessions = (
        await session.execute(
            select(TrainingSession).where(TrainingSession.user_id == user.id).order_by(TrainingSession.performed_at),
        )
    ).scalars().all()
    assert len(sessions) == 2
    assert {s.source for s in sessions} == {SessionSource.PLAN}


async def test_heavy_block_b_progression_state_matches_resolve_next_targets(session, user: User):
    """Тот же принцип, что и в остальном проекте (см. CLAUDE.md "Стиль
    тестирования") — сверяем с реальным вызовом resolve_next_targets, не с
    цифрой, посчитанной руками."""
    await _onboard(session, user)
    workout_set = await _make_workout_set(session, user)
    workouts = WorkoutRepository(session)
    await workouts.record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=NOW - timedelta(days=3),
        block_a_reps=BlockLog(working_reps=(10, 10, 9), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=5),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.WEIGHT, block_b_equipment_value=Decimal("5.0"),
    )
    # workout_set.workouts_completed теперь 1 (нечётное) -> следующая блока Б тяжёлая.
    _state_a, expected_state_b = await WorkoutRepository(session).resolve_next_targets(user.id)
    assert expected_state_b.is_heavy is True  # проверка предпосылки теста

    await backfill_all(session, now=NOW)

    plan = (await session.execute(select(TrainingPlan).where(TrainingPlan.user_id == user.id))).scalar_one()
    inclusion = (
        await session.execute(select(ProgramInclusion).where(ProgramInclusion.training_plan_id == plan.id))
    ).scalar_one()
    block_b = inclusion.progression_state["block_b"]
    assert block_b["is_heavy_next"] is True
    assert block_b["heavy_equipment_value_next"] == str(expected_state_b.heavy_equipment_value)


async def test_free_entry_transfers_only_block_a(session, user: User):
    await _onboard(session, user)
    workout_set = await _make_workout_set(session, user)
    await WorkoutRepository(session).record_free_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=NOW - timedelta(days=1),
        block_a_reps=BlockLog(working_reps=(15, 12), max_reps=18),
        equipment_type=EquipmentType.BODYWEIGHT,
    )

    await backfill_all(session, now=NOW)

    training_session = (
        await session.execute(select(TrainingSession).where(TrainingSession.user_id == user.id))
    ).scalar_one()
    assert training_session.source == SessionSource.FREEFORM
    blocks = (
        await session.execute(select(SessionBlock).where(SessionBlock.session_id == training_session.id))
    ).scalars().all()
    assert len(blocks) == 1
    logs = (await session.execute(select(SetLog).where(SetLog.session_block_id == blocks[0].id))).scalars().all()
    assert sorted(int(log.value) for log in logs) == [12, 15, 18]


async def test_backdated_reported_volume_uses_reported_total_not_raw_max(session, user: User):
    await _onboard(session, user)
    workout_set = await _make_workout_set(session, user)
    await WorkoutRepository(session).record_backdated_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=NOW - timedelta(days=7),
        block_a_reps=BlockLog(working_reps=(10, 10, 9), max_reps=11),
        block_b_reps=BlockLog(working_reps=(), max_reps=0, reported_volume=42),
        block_a_equipment_type=EquipmentType.BODYWEIGHT, block_a_equipment_value=None,
        block_b_equipment_type=EquipmentType.BODYWEIGHT, block_b_equipment_value=None,
    )

    await backfill_all(session, now=NOW)

    training_session = (
        await session.execute(select(TrainingSession).where(TrainingSession.user_id == user.id))
    ).scalar_one()
    assert training_session.source == SessionSource.BACKDATED
    blocks = (
        await session.execute(
            select(SessionBlock).where(SessionBlock.session_id == training_session.id).order_by(SessionBlock.order_index),
        )
    ).scalars().all()
    assert len(blocks) == 2
    block_b_logs = (await session.execute(select(SetLog).where(SetLog.session_block_id == blocks[1].id))).scalars().all()
    # max_reps=0 -> максимум не зафиксирован, единственный SetLog — итог.
    assert len(block_b_logs) == 1
    assert block_b_logs[0].value == 42
    assert block_b_logs[0].note == "итог без раскладки по подходам"


async def test_all_four_elective_formats_transfer_one_session_each(session, user: User):
    await _onboard(session, user)
    electives = ElectiveWorkoutRepository(session)
    await electives.create(
        user_id=user.id, elective_type=ElectiveType.MAX_REPS_LADDER, performed_at=NOW - timedelta(days=1),
        total_reps=36, reps_sequence=[12, 10, 8, 6], equipment_type=EquipmentType.BAND, equipment_value=BAND_VALUE,
    )
    await electives.create(
        user_id=user.id, elective_type=ElectiveType.W_LADDER, performed_at=NOW - timedelta(days=2),
        total_reps=51, reps_sequence=list(range(1, 6)) * 2 + [5], equipment_type=EquipmentType.BODYWEIGHT,
    )
    await electives.create(
        user_id=user.id, elective_type=ElectiveType.THREE_MINUTES, performed_at=NOW - timedelta(days=3),
        total_reps=40, reps_sequence=[7, 7, 7, 6, 7, 6], equipment_type=EquipmentType.BODYWEIGHT,
    )
    await electives.create(
        user_id=user.id, elective_type=ElectiveType.VOLUME_TARGET, performed_at=NOW - timedelta(days=4),
        total_reps=50, reps_sequence=None, equipment_type=EquipmentType.BODYWEIGHT,
    )

    await backfill_all(session, now=NOW)

    sessions = (
        await session.execute(select(TrainingSession).where(TrainingSession.user_id == user.id))
    ).scalars().all()
    assert len(sessions) == 4
    assert {s.source for s in sessions} == {SessionSource.ELECTIVE}

    for training_session in sessions:
        block = (
            await session.execute(select(SessionBlock).where(SessionBlock.session_id == training_session.id))
        ).scalar_one()
        logs = (await session.execute(select(SetLog).where(SetLog.session_block_id == block.id))).scalars().all()
        assert len(logs) == 1  # "по одной... на каждую" (issue #163, п.3)
        note = json.loads(logs[0].note)
        if note["format"] == ElectiveType.VOLUME_TARGET.value:
            assert note["reps_sequence"] is None
            assert int(logs[0].value) == 50


async def test_seed_catalog_is_idempotent_by_name(session):
    first = await seed_catalog(session)
    second = await seed_catalog(session)

    assert first.program_id == second.program_id
    assert first.exercise_a_id == second.exercise_a_id
    assert first.elective_exercise_ids == second.elective_exercise_ids
    assert len((await session.execute(select(Program))).scalars().all()) == 1
    assert len((await session.execute(select(Exercise))).scalars().all()) == 6  # 2 программных + 4 факультатива


async def test_backfill_is_idempotent_on_second_run(session, user: User):
    await _onboard(session, user)
    workout_set = await _make_workout_set(session, user)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=NOW - timedelta(days=5),
        block_a_reps=BlockLog(working_reps=(10, 10, 9), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )

    await backfill_all(session, now=NOW)
    plans_after_first = len((await session.execute(select(TrainingPlan))).scalars().all())
    sessions_after_first = len((await session.execute(select(TrainingSession))).scalars().all())

    report_second = await backfill_all(session, now=NOW)

    plans_after_second = len((await session.execute(select(TrainingPlan))).scalars().all())
    sessions_after_second = len((await session.execute(select(TrainingSession))).scalars().all())
    assert plans_after_second == plans_after_first == 1
    assert sessions_after_second == sessions_after_first == 1
    assert report_second.users_migrated_this_run == 0
    assert report_second.users_already_migrated == 1


async def test_truncate_then_rerun_recreates_data_without_duplicates(session, user: User):
    await _onboard(session, user)
    workout_set = await _make_workout_set(session, user)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=NOW - timedelta(days=5),
        block_a_reps=BlockLog(working_reps=(10, 10, 9), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )

    await backfill_all(session, now=NOW)
    await session.execute(text("TRUNCATE TABLE training_plans, training_sessions RESTART IDENTITY CASCADE"))
    await session.commit()

    report = await backfill_all(session, now=NOW)

    assert report.users_migrated_this_run == 1
    assert len((await session.execute(select(TrainingPlan))).scalars().all()) == 1
    assert len((await session.execute(select(TrainingSession))).scalars().all()) == 1


async def test_readiness_report_reconciles_counts_for_multiple_users(session, user: User):
    """Буквальный критерий готовности issue #163: число TrainingPlan равно
    числу онбордившихся, число перенесённых TrainingSession (обычных +
    elective) сходится с числом строк в старых таблицах."""
    await _onboard(session, user)
    workout_set = await _make_workout_set(session, user)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=NOW - timedelta(days=5),
        block_a_reps=BlockLog(working_reps=(10, 10, 9), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )
    await ElectiveWorkoutRepository(session).create(
        user_id=user.id, elective_type=ElectiveType.VOLUME_TARGET, performed_at=NOW - timedelta(days=2),
        total_reps=50, reps_sequence=None, equipment_type=EquipmentType.BODYWEIGHT,
    )

    second_user = await UserRepository(session).create(telegram_id=1002, username="second")
    await _onboard(session, second_user)  # без единой тренировки

    report = await backfill_all(session, now=NOW)

    assert report.training_plans_total == report.users_onboarded == 2
    assert report.training_sessions_regular_total == report.workouts_completed_expected == 1
    assert report.training_sessions_elective_total == report.electives_expected == 1
    rendered = report.render()
    assert rendered.count("[OK]") == 3
    assert "РАСХОЖДЕНИЕ" not in rendered


async def test_dry_run_does_not_write_anything(session, user: User):
    await _onboard(session, user)
    workout_set = await _make_workout_set(session, user)
    await WorkoutRepository(session).record_workout(
        user_id=user.id, workout_set_id=workout_set.id, performed_at=NOW - timedelta(days=5),
        block_a_reps=BlockLog(working_reps=(10, 10, 9), max_reps=11),
        block_b_reps=BlockLog(working_reps=(3, 3, 3, 3), max_reps=3),
        block_a_equipment_type=EquipmentType.BAND, block_a_equipment_value=BAND_VALUE,
        block_b_equipment_type=EquipmentType.BAND, block_b_equipment_value=BAND_VALUE,
    )

    report = await backfill_all(session, now=NOW, dry_run=True)

    assert report.users_migrated_this_run == 1
    assert report.training_sessions_regular_total == 1
    assert (await session.execute(select(TrainingPlan))).scalars().all() == []
    assert (await session.execute(select(TrainingSession))).scalars().all() == []
    assert (await session.execute(select(Program))).scalars().all() == []
