"""GET/POST /api/v2/sessions (issue #165, волна 3) — пишет факт всегда,
пересчитывает ProgramInclusion.progression_state ТОЛЬКО для STEP-стратегии
с блоками, покрывающими обе роли block_a/block_b. Числа сверены с прямым
вызовом StepProgressionStrategy.apply() (тот же приём "доказательство не
копии", что test_submit_uses_same_progression_as_direct_repository_call в
tests/test_web/test_workout.py), не выведены из самого HTTP-слоя."""

from datetime import UTC, datetime

from app.db.models import User
from app.db.models_program import Exercise, Program, ProgressionStrategyProfile
from app.domain.constants import EquipmentType
from app.domain.multi_program import MetricType, ProgramStructureType
from app.domain.progression_strategy import (
    ProgressionContext,
    ProgressionStrategyType,
    StepProgressionStrategy,
)
from app.domain.session import BlockAssignment, BlockLog, WorkoutRecord
from tests.test_web._v2_client import v2_get, v2_post


async def _make_step_program(session, *, category: str = "pullups_sessions") -> Program:
    profile = ProgressionStrategyProfile(strategy_type=ProgressionStrategyType.STEP, name="Step", config={})
    session.add(profile)
    await session.flush()
    program = Program(
        name="Синтетика сессий", goal="test", structure_type=ProgramStructureType.RECURRING,
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


async def test_create_session_for_unknown_telegram_id_is_404(session):
    response = await v2_post(
        session, telegram_id=60401, path="/api/v2/sessions",
        payload={
            "source": "freeform", "performed_at": "2026-01-01T00:00:00Z",
            "blocks": [_sets_block(1, [5], 6)],
        },
    )
    assert response.status_code == 404


async def test_create_session_for_unknown_program_inclusion_is_404(session, user: User):
    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions",
        payload={
            "source": "plan", "performed_at": "2026-01-01T00:00:00Z", "program_inclusion_id": 999999,
            "blocks": [_sets_block(1, [5], 6)],
        },
    )
    assert response.status_code == 404


async def test_create_session_applies_step_progression_matching_direct_strategy_call(session, user: User):
    program = await _make_step_program(session)
    inclusion = await _create_inclusion(session, user.telegram_id, program.id)
    roles = _exercise_ids_by_role(inclusion)

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions",
        payload={
            "source": "plan", "performed_at": "2026-01-05T10:00:00Z",
            "program_inclusion_id": inclusion["id"],
            "blocks": [
                _sets_block(roles["block_a"], [11, 11, 11], 12),
                _sets_block(roles["block_b"], [4, 4, 4, 4], 4),
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["progression_skipped_reason"] is None
    assert body["progression_result"] is not None

    # --- reference: тот же расчёт напрямую через StepProgressionStrategy ---
    record = WorkoutRecord(
        performed_at=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
        block_a=BlockAssignment(
            log=BlockLog(working_reps=(11, 11, 11), max_reps=12),
            target_before=10, target_after=10, equipment_changed=False, equipment_type=EquipmentType.BODYWEIGHT,
        ),
        block_b=BlockAssignment(
            log=BlockLog(working_reps=(4, 4, 4, 4), max_reps=4),
            target_before=3, target_after=3, equipment_changed=False, equipment_type=EquipmentType.BODYWEIGHT,
        ),
    )
    context = ProgressionContext(
        starting_target_a=10, starting_target_b=3, starting_volume_a=0, starting_volume_b=0,
        subsequent_workouts=[record], starting_work_sets_a=3,
    )
    [reference] = StepProgressionStrategy().apply(context)

    assert body["progression_result"]["block_a"]["target_before"] == reference.block_a.target_before
    assert body["progression_result"]["block_a"]["target_after"] == reference.block_a.target_after
    assert body["progression_result"]["block_b"]["target_before"] == reference.block_b.target_before
    assert body["progression_result"]["block_b"]["target_after"] == reference.block_b.target_after

    # progression_state на инклюзии обновлено этими же значениями.
    plan_response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")
    state = plan_response.json()["plan"]["program_inclusions"][0]["progression_state"]
    assert state["block_a"]["target"] == reference.block_a.target_after
    assert state["block_a"]["volume"] == 45  # 11+11+11+12
    assert state["block_b"]["target"] == reference.block_b.target_after
    assert state["block_b"]["volume"] == 20  # 4*4+4


async def test_create_session_without_inclusion_only_writes_fact(session, user: User):
    program = await _make_step_program(session)
    inclusion = await _create_inclusion(session, user.telegram_id, program.id)
    roles = _exercise_ids_by_role(inclusion)

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions",
        payload={
            "source": "freeform", "performed_at": "2026-01-05T10:00:00Z",
            "blocks": [_sets_block(roles["block_a"], [20], 22)],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["progression_result"] is None
    assert body["progression_skipped_reason"] == "no_program_inclusion"

    plan_response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")
    state = plan_response.json()["plan"]["program_inclusions"][0]["progression_state"]
    assert state["block_a"]["target"] == 10  # не изменилось - прогрессия не применялась


async def test_create_session_with_non_step_inclusion_skips_progression(session, user: User):
    program = Program(
        name="Без стратегии", goal="test", structure_type=ProgramStructureType.SINGLE_LESSON,
        category="no_strategy_synth", config={},
    )
    session.add(program)
    await session.flush()
    exercise = Exercise(name="Одиночное", metric_type=MetricType.REPS, category="no_strategy_synth")
    session.add(exercise)
    await session.flush()
    inclusion = await _create_inclusion(session, user.telegram_id, program.id)
    assert inclusion["progression_state"] == {}

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions",
        payload={
            "source": "plan", "performed_at": "2026-01-05T10:00:00Z",
            "program_inclusion_id": inclusion["id"],
            "blocks": [_sets_block(exercise.id, [10], 11)],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["progression_result"] is None
    assert body["progression_skipped_reason"] == "not_step_strategy"


async def test_create_session_with_blocks_not_matching_step_roles_skips_progression(session, user: User):
    program = await _make_step_program(session)
    inclusion = await _create_inclusion(session, user.telegram_id, program.id)
    roles = _exercise_ids_by_role(inclusion)

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions",
        payload={
            "source": "plan", "performed_at": "2026-01-05T10:00:00Z",
            "program_inclusion_id": inclusion["id"],
            # Только один блок вместо двух ролей - не покрывает block_a/block_b.
            "blocks": [_sets_block(roles["block_a"], [11, 11, 11], 12)],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["progression_result"] is None
    assert body["progression_skipped_reason"] == "blocks_do_not_match_step_roles"


async def test_list_sessions_returns_recorded_history(session, user: User):
    program = await _make_step_program(session)
    inclusion = await _create_inclusion(session, user.telegram_id, program.id)
    roles = _exercise_ids_by_role(inclusion)

    await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions",
        payload={
            "source": "plan", "performed_at": "2026-01-05T10:00:00Z", "program_inclusion_id": inclusion["id"],
            "comment": "норм", "effort": "7.5",
            "blocks": [
                _sets_block(roles["block_a"], [11, 11, 11], 12), _sets_block(roles["block_b"], [4, 4, 4, 4], 4),
            ],
        },
    )

    list_response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions")
    assert list_response.status_code == 200
    sessions = list_response.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["source"] == "plan"
    assert sessions[0]["comment"] == "норм"
    assert sessions[0]["effort"] == "7.5"
    assert len(sessions[0]["blocks"]) == 2
    assert [s["value"] for s in sessions[0]["blocks"][0]["set_logs"]] == ["11", "11", "11", "12"]


async def test_create_session_rejects_ambiguous_target(session, user: User):
    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions",
        payload={
            "source": "freeform", "performed_at": "2026-01-01T00:00:00Z",
            "blocks": [{"exercise_id": 1, "complex_id": 1, "sets": [
                {"set_number": 1, "metric_type": "reps", "value": "5", "unit": "reps"},
            ]}],
        },
    )
    assert response.status_code == 422
