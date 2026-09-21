"""GET /api/v2/sessions — Checkpoint 4C (issue #188): status-фильтр и
резолв source-заголовка через SessionPlanItem -> PlanItem ->
(ProgramInclusion | Exercise), одна и та же таблица SessionPlanItem,
заполняемая с Checkpoint 4A, впервые прочитанная здесь.

Использует _setup_step_session из test_v2_live_session.py для
program-backed сценария (та же фикстура, не дублирует настройку STEP-
программы) — только живой /sessions/live путь реально заполняет
SessionPlanItem (в отличие от легаси POST /sessions, см.
test_v2_sessions.py::test_list_sessions_returns_recorded_history, там
title всегда None — проверено отдельно ниже)."""

import uuid

from app.db.models import User
from app.db.models_program import Exercise, PlanItem
from app.db.repositories.training_plans import TrainingPlanRepository
from app.db.repositories.users import UserRepository
from app.domain.multi_program import MetricType
from tests.test_web._v2_client import v2_get, v2_post
from tests.test_web.test_v2_live_session import _setup_step_session


async def _start_and_complete(session, user: User, plan_item_ids: list[int], *, exercise_id: int, value: str):
    start = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={"client_session_id": str(uuid.uuid4()), "plan_item_ids": plan_item_ids},
    )
    assert start.status_code == 200
    session_id = start.json()["id"]
    batch = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/sets:batch",
        payload={"sets": [{"set_index": 0, "exercise_id": exercise_id, "value": value}]},
    )
    assert batch.status_code == 200
    complete = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/complete",
        payload={"abandoned": False},
    )
    assert complete.status_code == 200
    return session_id


async def _make_manual_plan_item(session, user: User, *, name: str, metric_type: MetricType) -> int:
    exercise = Exercise(name=name, metric_type=metric_type, category="checkpoint4c")
    session.add(exercise)
    await session.flush()
    plan = await TrainingPlanRepository(session).get_or_create_for_user(user.id)
    item = PlanItem(
        training_plan_id=plan.id, exercise_id=exercise.id, count_per_week=1,
        day_of_week=None, program_inclusion_id=None,
    )
    session.add(item)
    await session.flush()
    return item.id


async def test_status_filter_excludes_started(session, user: User):
    _, _, plan_item_ids = await _setup_step_session(session, user)
    await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={
            "client_session_id": str(uuid.uuid4()),
            "plan_item_ids": [plan_item_ids["block_a"], plan_item_ids["block_b"]],
        },
    )  # намеренно не завершена — остаётся STARTED

    completed_only = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions?status=completed")
    assert completed_only.status_code == 200
    assert completed_only.json()["sessions"] == []

    started_only = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions?status=started")
    assert len(started_only.json()["sessions"]) == 1


async def test_status_filter_omitted_keeps_old_behavior(session, user: User):
    _, _, plan_item_ids = await _setup_step_session(session, user)
    await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={
            "client_session_id": str(uuid.uuid4()),
            "plan_item_ids": [plan_item_ids["block_a"], plan_item_ids["block_b"]],
        },
    )

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions")
    assert response.status_code == 200
    assert len(response.json()["sessions"]) == 1  # STARTED всё ещё видна без фильтра


async def test_program_backed_session_title_is_program_name_not_block_name(session, user: User):
    inclusion, roles, plan_item_ids = await _setup_step_session(session, user)
    session_id = await _start_and_complete(
        session, user, [plan_item_ids["block_a"], plan_item_ids["block_b"]],
        exercise_id=roles["block_a"], value="10",
    )

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions?status=completed")
    sessions = response.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["id"] == session_id
    assert sessions[0]["title"] == inclusion["program_name"]
    assert sessions[0]["title"] != "Блок A"
    assert sessions[0]["title"] != "Блок Б"


async def test_manual_time_session_title_is_exercise_name(session, user: User):
    plank_id = await _make_manual_plan_item(session, user, name="Планка", metric_type=MetricType.TIME)

    plan = await TrainingPlanRepository(session).get_for_user(user.id)
    items = await TrainingPlanRepository(session).list_plan_items(plan.id)
    exercise_id = next(item.exercise_id for item in items if item.id == plank_id)

    session_id = await _start_and_complete(session, user, [plank_id], exercise_id=exercise_id, value="30")

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions?status=completed")
    sessions = response.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["id"] == session_id
    assert sessions[0]["title"] == "Планка"


async def test_manual_reps_session_title_is_exercise_name(session, user: User):
    pushups_id = await _make_manual_plan_item(session, user, name="Отжимания", metric_type=MetricType.REPS)
    plan = await TrainingPlanRepository(session).get_for_user(user.id)
    items = await TrainingPlanRepository(session).list_plan_items(plan.id)
    exercise_id = next(item.exercise_id for item in items if item.id == pushups_id)

    session_id = await _start_and_complete(session, user, [pushups_id], exercise_id=exercise_id, value="15")

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions?status=completed")
    sessions = response.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["id"] == session_id
    assert sessions[0]["title"] == "Отжимания"


async def test_session_without_session_plan_item_has_null_title(session, user: User):
    """Легаси POST /sessions (не /sessions/live) не заполняет
    SessionPlanItem вообще — честный None, не выдуманное имя."""
    inclusion, roles, _ = await _setup_step_session(session, user)
    await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions",
        payload={
            "source": "plan", "performed_at": "2026-01-05T10:00:00Z", "program_inclusion_id": inclusion["id"],
            "blocks": [
                {
                    "exercise_id": roles["block_a"],
                    "sets": [{"set_number": 1, "metric_type": "reps", "value": "10", "unit": "reps"}],
                },
            ],
        },
    )

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions?status=completed")
    sessions = response.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["title"] is None


async def test_journal_never_leaks_foreign_users_session(session, user: User):
    other = await UserRepository(session).create(telegram_id=user.telegram_id + 1, username="other4c")
    plank_id = await _make_manual_plan_item(session, other, name="Чужая планка", metric_type=MetricType.TIME)
    plan = await TrainingPlanRepository(session).get_for_user(other.id)
    items = await TrainingPlanRepository(session).list_plan_items(plan.id)
    exercise_id = next(item.exercise_id for item in items if item.id == plank_id)
    await _start_and_complete(session, other, [plank_id], exercise_id=exercise_id, value="30")

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions?status=completed")
    assert response.json()["sessions"] == []
