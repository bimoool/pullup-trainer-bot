"""POST/GET /api/v2/sessions/live/* (issue #165, продолжение волны 3 —
"сессия — live", раздел 12 docs/plan-and-specs.md) — офлайн-контракт
проверяется буквально: идемпотентность старта по client_session_id,
переход фазы НИКОГДА не ошибка при рассинхроне expected_phase_index,
батч подходов идемпотентен по (session_id, set_index). Завершение сверяется
с прямым вызовом StepProgressionStrategy тем же приёмом "доказательство не
копии", что и tests/test_web/test_v2_sessions.py::
test_create_session_applies_step_progression_matching_direct_strategy_call
— цифры должны совпасть с движком, не только "не упасть".

Батч этой волны (LiveSetBatchEntry/BatchSetLogInput) намеренно не несёт
is_max_set (см. раздел 12 контракта и app.web.schemas_v2_session) — все
подходы, залогированные через sets:batch, попадают в working_reps
BlockLog'а, max_reps всегда 0. Тесты ниже поэтому используют фикстуры БЕЗ
подхода "на максимум" и в reference-вызове, и в живой сессии — сравнение
остаётся честным (то же самое отсутствие max-подхода с обеих сторон), а не
скрывает этот известный пробел контракта."""

import uuid
from datetime import UTC, datetime

from app.db.models import User
from app.db.models_program import Exercise, PlanItem, Program, ProgressionStrategyProfile
from app.db.repositories.training_plans import TrainingPlanRepository
from app.domain.constants import EquipmentType
from app.domain.multi_program import MetricType, ProgramStructureType
from app.domain.progression_strategy import (
    ProgressionContext,
    ProgressionStrategyType,
    StepProgressionStrategy,
)
from app.domain.session import BlockAssignment, BlockLog, WorkoutRecord
from tests.test_web._v2_client import v2_get, v2_post


async def _make_step_program(session, *, category: str = "live_sessions") -> Program:
    profile = ProgressionStrategyProfile(strategy_type=ProgressionStrategyType.STEP, name="Step", config={})
    session.add(profile)
    await session.flush()
    program = Program(
        name="Синтетика живой сессии", goal="test", structure_type=ProgramStructureType.RECURRING,
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


async def _setup_step_session(session, user: User) -> tuple[dict, dict[str, int], dict[str, int]]:
    """Возвращает (инклюзия, exercise_id по роли, plan_item_id по роли).
    PlanItem для ролей создаются напрямую (не через ProgramItem/бэкфилл —
    _make_step_program синтетическая, без ProgramItem) — тот же приём, что
    и остальные test_v2_*-фикстуры, добавляющие модели напрямую в общую
    сессию, которую переопределение зависимости get_session отдаёт и
    HTTP-вызовам."""
    program = await _make_step_program(session)
    inclusion = await _create_inclusion(session, user.telegram_id, program.id)
    roles = _exercise_ids_by_role(inclusion)

    plans = TrainingPlanRepository(session)
    plan = await plans.get_for_user(user.id)
    plan_item_ids: dict[str, int] = {}
    for role, exercise_id in roles.items():
        item = PlanItem(
            training_plan_id=plan.id, exercise_id=exercise_id, count_per_week=3,
            program_inclusion_id=inclusion["id"],
        )
        session.add(item)
        await session.flush()
        plan_item_ids[role] = item.id
    return inclusion, roles, plan_item_ids


async def test_start_live_session_for_unknown_plan_item_is_404(session, user: User):
    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": [999999]},
    )
    assert response.status_code == 404


async def test_start_live_session_returns_get_ready_phase_with_step_targets(session, user: User):
    _, roles, plan_item_ids = await _setup_step_session(session, user)

    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={
            "client_session_id": str(uuid.uuid4()),
            "plan_item_ids": [plan_item_ids["block_a"], plan_item_ids["block_b"]],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "started"
    assert body["phase"]["name"] == "get_ready"
    assert body["phase"]["ends_at"] is not None
    assert body["phase_index"] == 0
    assert body["current_block_index"] == 0
    assert body["current_set_number"] == 1
    assert len(body["blocks"]) == 2

    block_a = next(b for b in body["blocks"] if b["exercise_id"] == roles["block_a"])
    # base_target=10, work_sets=3 (config _make_step_program) -> 3 таргета по 10.
    assert [t["value"] for t in block_a["targets"]] == ["10.00", "10.00", "10.00"]
    block_b = next(b for b in body["blocks"] if b["exercise_id"] == roles["block_b"])
    # block_b не хранит work_sets в progression_state -> дефолт 1 подход (см.
    # app.services.live_session._resolve_step_role_block).
    assert [t["value"] for t in block_b["targets"]] == ["3.00"]


async def test_start_live_session_is_idempotent_by_client_session_id(session, user: User):
    _, _, plan_item_ids = await _setup_step_session(session, user)
    client_session_id = str(uuid.uuid4())
    payload = {"client_session_id": client_session_id, "plan_item_ids": [plan_item_ids["block_a"]]}

    first = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/sessions/live", payload=payload)
    second = await v2_post(session, telegram_id=user.telegram_id, path="/api/v2/sessions/live", payload=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]  # не создало вторую сессию


async def test_advance_phase_transitions_when_expected_index_matches(session, user: User):
    _, _, plan_item_ids = await _setup_step_session(session, user)
    start = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": [plan_item_ids["block_a"]]},
    )
    session_id = start.json()["id"]
    assert start.json()["phase"]["name"] == "get_ready"

    response = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/phase/next",
        payload={"expected_phase_index": 0},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["phase"]["name"] == "go"  # get_ready -> go, без таймера
    assert body["phase"]["ends_at"] is None
    assert body["phase_index"] == 1


async def test_advance_phase_with_stale_expected_index_does_not_transition(session, user: User):
    _, _, plan_item_ids = await _setup_step_session(session, user)
    start = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": [plan_item_ids["block_a"]]},
    )
    session_id = start.json()["id"]
    await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/phase/next",
        payload={"expected_phase_index": 0},
    )  # сервер теперь на phase_index=1 (go)

    stale = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/phase/next",
        payload={"expected_phase_index": 0},  # клиент отстал - это уже пройденный индекс
    )

    assert stale.status_code == 200  # НЕ 409
    body = stale.json()
    assert body["phase"]["name"] == "go"  # не откатилось назад
    assert body["phase_index"] == 1  # не увеличилось повторно


async def test_advance_phase_with_future_expected_index_does_not_transition(session, user: User):
    _, _, plan_item_ids = await _setup_step_session(session, user)
    start = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": [plan_item_ids["block_a"]]},
    )
    session_id = start.json()["id"]

    future = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/phase/next",
        payload={"expected_phase_index": 5},  # клиент "обогнал" сервер
    )

    assert future.status_code == 200  # НЕ 409
    body = future.json()
    assert body["phase"]["name"] == "get_ready"  # не перешло
    assert body["phase_index"] == 0


async def test_advance_phase_for_nonexistent_session_is_404(session, user: User):
    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live/999999/phase/next",
        payload={"expected_phase_index": 0},
    )
    assert response.status_code == 404


async def test_batch_sets_resend_identical_is_noop_resend_different_overwrites(session, user: User):
    _, roles, plan_item_ids = await _setup_step_session(session, user)
    start = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": [plan_item_ids["block_a"]]},
    )
    session_id = start.json()["id"]
    exercise_id = roles["block_a"]
    batch_path = f"/api/v2/sessions/live/{session_id}/sets:batch"

    payload = {"sets": [{"set_index": 0, "exercise_id": exercise_id, "value": "11"}]}
    first = await v2_post(session, telegram_id=user.telegram_id, path=batch_path, payload=payload)
    second = await v2_post(session, telegram_id=user.telegram_id, path=batch_path, payload=payload)  # тот же батч

    assert first.status_code == 200
    assert second.status_code == 200
    logs = second.json()["blocks"][0]["set_logs"]
    assert len(logs) == 1  # не задублировался
    assert logs[0]["value"] == "11.00"

    overwrite_payload = {"sets": [{"set_index": 0, "exercise_id": exercise_id, "value": "13", "note": "правка"}]}
    overwrite = await v2_post(session, telegram_id=user.telegram_id, path=batch_path, payload=overwrite_payload)

    assert overwrite.status_code == 200
    logs = overwrite.json()["blocks"][0]["set_logs"]
    assert len(logs) == 1  # правка, не вторая строка
    assert logs[0]["value"] == "13.00"
    assert logs[0]["note"] == "правка"


async def test_batch_sets_assigns_sequential_set_number_within_batch(session, user: User):
    _, roles, plan_item_ids = await _setup_step_session(session, user)
    start = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": [plan_item_ids["block_a"]]},
    )
    session_id = start.json()["id"]
    exercise_id = roles["block_a"]

    response = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/sets:batch",
        payload={"sets": [
            {"set_index": 0, "exercise_id": exercise_id, "value": "11"},
            {"set_index": 1, "exercise_id": exercise_id, "value": "12"},
            {"set_index": 2, "exercise_id": exercise_id, "value": "13"},
        ]},
    )

    assert response.status_code == 200
    logs = sorted(response.json()["blocks"][0]["set_logs"], key=lambda log: log["set_number"])
    assert [log["set_number"] for log in logs] == [1, 2, 3]
    assert [log["value"] for log in logs] == ["11.00", "12.00", "13.00"]


async def test_batch_sets_for_foreign_session_is_404(session, user: User):
    other = User(telegram_id=99999997, username="other")
    session.add(other)
    await session.flush()
    _, roles, plan_item_ids = await _setup_step_session(session, user)
    start = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": [plan_item_ids["block_a"]]},
    )
    session_id = start.json()["id"]

    response = await v2_post(
        session, telegram_id=other.telegram_id, path=f"/api/v2/sessions/live/{session_id}/sets:batch",
        payload={"sets": [{"set_index": 0, "exercise_id": roles["block_a"], "value": "11"}]},
    )

    assert response.status_code == 404


async def test_batch_sets_for_nonexistent_session_is_404(session, user: User):
    response = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live/999999/sets:batch",
        payload={"sets": [{"set_index": 0, "exercise_id": 1, "value": "11"}]},
    )
    assert response.status_code == 404


async def test_get_active_live_session_returns_null_when_none(session, user: User):
    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions/live/active")

    assert response.status_code == 200
    assert response.json()["session"] is None


async def test_get_active_live_session_returns_started_session(session, user: User):
    _, _, plan_item_ids = await _setup_step_session(session, user)
    start = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": [plan_item_ids["block_a"]]},
    )

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions/live/active")

    assert response.status_code == 200
    assert response.json()["session"]["id"] == start.json()["id"]


async def test_complete_live_session_for_foreign_session_is_404(session, user: User):
    other = User(telegram_id=99999996, username="other2")
    session.add(other)
    await session.flush()
    _, _, plan_item_ids = await _setup_step_session(session, user)
    start = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": [plan_item_ids["block_a"]]},
    )
    session_id = start.json()["id"]

    response = await v2_post(
        session, telegram_id=other.telegram_id, path=f"/api/v2/sessions/live/{session_id}/complete",
        payload={"abandoned": False},
    )

    assert response.status_code == 404


async def test_complete_live_session_abandoned_skips_progression(session, user: User):
    _, roles, plan_item_ids = await _setup_step_session(session, user)
    start = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={
            "client_session_id": str(uuid.uuid4()),
            "plan_item_ids": [plan_item_ids["block_a"], plan_item_ids["block_b"]],
        },
    )
    session_id = start.json()["id"]
    await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/sets:batch",
        payload={"sets": [{"set_index": 0, "exercise_id": roles["block_a"], "value": "11"}]},
    )

    response = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/complete",
        payload={"abandoned": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["progression_result"] is None
    assert body["progression_skipped_reason"] == "abandoned"


async def test_complete_live_session_applies_step_progression_matching_direct_strategy_call(session, user: User):
    """Тот же приём "доказательство не копии", что
    tests/test_web/test_v2_sessions.py::
    test_create_session_applies_step_progression_matching_direct_strategy_call
    — цифры пути "живая сессия -> complete" должны СОВПАСТЬ с прямым
    вызовом StepProgressionStrategy на тех же входных подходах, не просто
    не упасть. Без подхода "на максимум" — batch-контракт этой волны не
    несёт is_max_set (см. докстринг модуля), max_reps=0 с обеих сторон
    сравнения, иначе сравнение было бы нечестным (по конструкции не может
    разойтись именно из-за max-подхода)."""
    inclusion, roles, plan_item_ids = await _setup_step_session(session, user)

    start = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={
            "client_session_id": str(uuid.uuid4()),
            "plan_item_ids": [plan_item_ids["block_a"], plan_item_ids["block_b"]],
        },
    )
    session_id = start.json()["id"]

    batch = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/sets:batch",
        payload={"sets": [
            {"set_index": 0, "exercise_id": roles["block_a"], "value": "11"},
            {"set_index": 1, "exercise_id": roles["block_a"], "value": "11"},
            {"set_index": 2, "exercise_id": roles["block_a"], "value": "11"},
            {"set_index": 3, "exercise_id": roles["block_b"], "value": "4"},
            {"set_index": 4, "exercise_id": roles["block_b"], "value": "4"},
            {"set_index": 5, "exercise_id": roles["block_b"], "value": "4"},
            {"set_index": 6, "exercise_id": roles["block_b"], "value": "4"},
        ]},
    )
    assert batch.status_code == 200

    complete = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/complete",
        payload={"abandoned": False},
    )
    assert complete.status_code == 200
    body = complete.json()
    assert body["status"] == "completed"
    assert body["progression_skipped_reason"] is None
    assert body["progression_result"] is not None

    # --- reference: тот же расчёт напрямую через StepProgressionStrategy ---
    record = WorkoutRecord(
        performed_at=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
        block_a=BlockAssignment(
            log=BlockLog(working_reps=(11, 11, 11), max_reps=0),
            target_before=10, target_after=10, equipment_changed=False, equipment_type=EquipmentType.BODYWEIGHT,
        ),
        block_b=BlockAssignment(
            log=BlockLog(working_reps=(4, 4, 4, 4), max_reps=0),
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

    # progression_state инклюзии обновлено этими же значениями (тот же
    # инвариант, что тест wave-3 проверяет для одноразового пути).
    plan_response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/plan")
    inclusions = plan_response.json()["plan"]["program_inclusions"]
    updated = next(i for i in inclusions if i["id"] == inclusion["id"])
    assert updated["progression_state"]["block_a"]["target"] == reference.block_a.target_after
    assert updated["progression_state"]["block_b"]["target"] == reference.block_b.target_after
