"""REBUILD-1, R2 — Journal v2: данные каждого блока в GET /sessions,
серверный can_delete, безопасное удаление Builder-сессии, пагинация."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.models_program import (
    Complex,
    ComplexItem,
    Exercise,
    PlanItem,
    SessionBlock,
    SessionPlanItem,
    SetLog,
    SetTarget,
    TrainingSession,
)
from tests.test_web._v2_client import v2_delete, v2_get, v2_post
from tests.test_web.test_v2_live_session import _setup_step_session
from tests.test_web.test_v2_mixed_workout import (
    INTERVAL,
    MAX,
    REPS,
    _active,
    _backdate_block_start,
    _exercise,
    _run_standard_block,
    _start,
    _start_block,
    _user,
    _workout_plan_item,
)
from tests.test_web.test_v2_sessions_journal import _start_and_complete


async def _complete(session: AsyncSession, user: User, session_id: int) -> dict:
    response = await v2_post(
        session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/live/{session_id}/complete",
        payload={"abandoned": False},
    )
    assert response.status_code == 200
    return response.json()


async def _finished_mixed_session(session: AsyncSession, user: User) -> tuple[int, Complex]:
    """reps -> interval -> max, полностью пройденная и завершённая."""
    pull, burpee, push = (
        await _exercise(session, "Подтягивания"), await _exercise(session, "Бёрпи"), await _exercise(session, "Отжимания"),
    )
    plan_item_id, workout = await _workout_plan_item(session, user, [(pull, REPS), (burpee, INTERVAL), (push, MAX)])
    body = await _start(session, user, plan_item_id)
    body = await _run_standard_block(session, user, body, first_set_index=0, value="8")
    body = await _start_block(session, user, body, 1)
    await _backdate_block_start(session, body["id"], 1, 5 + 60 + 5)
    active = await _active(session, user)
    body = await _start_block(session, user, active, 2)
    body = await _run_standard_block(session, user, body, first_set_index=2, value="22")
    await _complete(session, user, body["id"])
    return body["id"], workout


async def test_list_exposes_independent_block_data_for_every_protocol(session: AsyncSession):
    user = await _user(session, 940001)
    session_id, _ = await _finished_mixed_session(session, user)

    response = await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions?status=completed")
    [card] = response.json()["sessions"]
    reps, interval, max_ = card["blocks"]

    assert [b["protocol_type"] for b in card["blocks"]] == ["reps_sets", "interval", "max_effort"]
    assert [b["exercise_name"] for b in card["blocks"]] == ["Подтягивания", "Бёрпи", "Отжимания"]
    assert [t["value"] for t in reps["set_targets"]] == ["8.00", "8.00"]
    assert [log["value"] for log in reps["set_logs"]] == ["8.00", "8.00"]
    assert interval["set_targets"] == [] and interval["set_logs"] == []
    assert interval["result"]["completed_cycles"] == 2
    assert interval["interval_config"] == {"total_duration_seconds": 60, "work_seconds": 10, "rest_seconds": 20}
    assert all(t["value"] == "0.00" and t["is_max_set"] for t in max_["set_targets"])  # цели нет, не план
    assert [log["value"] for log in max_["set_logs"]] == ["22.00", "22.00"]
    assert all(b["started_at"] is not None for b in card["blocks"])
    assert card["id"] == session_id and card["title"] == "Смешанная"


async def test_pagination_has_more_and_stable_offsets(session: AsyncSession):
    user = await _user(session, 940002)
    pull = await _exercise(session, "Подтягивания")
    plan_item_id, _ = await _workout_plan_item(session, user, [(pull, REPS)])
    ids = []
    for minutes_ago in range(5):
        body = await _start(session, user, plan_item_id)
        await _complete(session, user, body["id"])
        await session.execute(
            update(TrainingSession).where(TrainingSession.id == body["id"])
            .values(performed_at=datetime.now(UTC) - timedelta(minutes=minutes_ago)),
        )
        await session.commit()
        ids.append(body["id"])

    first = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions?status=completed&limit=2")).json()
    second = (await v2_get(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions?status=completed&limit=2&offset=2",
    )).json()
    last = (await v2_get(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions?status=completed&limit=2&offset=4",
    )).json()

    assert [s["id"] for s in first["sessions"]] == ids[:2] and first["has_more"] is True
    assert [s["id"] for s in second["sessions"]] == ids[2:4] and second["has_more"] is True
    assert [s["id"] for s in last["sessions"]] == ids[4:] and last["has_more"] is False


async def test_safe_delete_removes_only_the_session_tree(session: AsyncSession):
    user = await _user(session, 940003)
    session_id, workout = await _finished_mixed_session(session, user)

    listed = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions?status=completed")).json()
    assert listed["sessions"][0]["can_delete"] is True

    deleted = await v2_delete(session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/{session_id}")
    assert deleted.status_code == 204

    assert await session.scalar(select(func.count()).select_from(TrainingSession)) == 0
    for model in (SessionBlock, SetTarget, SetLog):
        assert await session.scalar(select(func.count()).select_from(model)) == 0
    # Определения и план целы: удаляется только дерево TrainingSession.
    assert await session.scalar(select(func.count()).select_from(Complex).where(Complex.id == workout.id)) == 1
    assert await session.scalar(select(func.count()).select_from(ComplexItem)) == 3
    assert await session.scalar(select(func.count()).select_from(Exercise)) >= 3
    assert await session.scalar(select(func.count()).select_from(PlanItem)) == 1

    again = await v2_delete(session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/{session_id}")
    assert again.status_code == 404


async def test_delete_denied_for_foreign_missing_active_and_unproven(session: AsyncSession):
    owner = await _user(session, 940004)
    stranger = await _user(session, 940005)
    session_id, _ = await _finished_mixed_session(session, owner)

    foreign = await v2_delete(session, telegram_id=stranger.telegram_id, path=f"/api/v2/sessions/{session_id}")
    missing = await v2_delete(session, telegram_id=owner.telegram_id, path="/api/v2/sessions/999999")
    assert foreign.status_code == 404 and missing.status_code == 404
    assert await session.scalar(select(func.count()).select_from(TrainingSession)) == 1  # чужую не удалили

    # Активная (STARTED) сессия — 409 с понятной причиной.
    pull = await _exercise(session, "Подтягивания2")
    plan_item_id, _ = await _workout_plan_item(session, owner, [(pull, REPS)], title="Ещё одна")
    running = await _start(session, owner, plan_item_id)
    active_try = await v2_delete(session, telegram_id=owner.telegram_id, path=f"/api/v2/sessions/{running['id']}")
    assert active_try.status_code == 409
    assert "завершите" in active_try.json()["detail"]

    # Недоказанная Builder-природа: завершённая сессия без снимка и без связи с Workout.
    await _complete(session, owner, running["id"])
    await session.execute(update(TrainingSession).where(TrainingSession.id == running["id"]).values(workout_snapshot=None))
    await session.execute(delete(SessionPlanItem).where(SessionPlanItem.session_id == running["id"]))
    await session.commit()
    unproven = await v2_delete(session, telegram_id=owner.telegram_id, path=f"/api/v2/sessions/{running['id']}")
    assert unproven.status_code == 409
    listed = (await v2_get(session, telegram_id=owner.telegram_id, path="/api/v2/sessions?status=completed")).json()
    flags = {s["id"]: s["can_delete"] for s in listed["sessions"]}
    assert flags[running["id"]] is False and flags[session_id] is True


async def test_step_session_is_protected_from_delete(session: AsyncSession, user: User):
    _, roles, plan_item_ids = await _setup_step_session(session, user)
    session_id = await _start_and_complete(
        session, user, [plan_item_ids["block_a"], plan_item_ids["block_b"]],
        exercise_id=roles["block_a"], value="10",
    )

    listed = (await v2_get(session, telegram_id=user.telegram_id, path="/api/v2/sessions?status=completed")).json()
    assert listed["sessions"][0]["can_delete"] is False

    response = await v2_delete(session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/{session_id}")
    assert response.status_code == 409
    assert "курс" in response.json()["detail"] or "прогресс" in response.json()["detail"]
    assert await session.scalar(select(func.count()).select_from(TrainingSession)) == 1


async def test_builder_session_touching_step_roles_is_protected(session: AsyncSession, user: User):
    """Даже если Builder-снимок доказан, блоки с ролями STEP A/B —
    отказ (страховка от удаления сессии, питающей прогрессию)."""
    _, roles, _ = await _setup_step_session(session, user)
    role_exercise = await session.get(Exercise, roles["block_a"])
    plan_item_id, _ = await _workout_plan_item(session, user, [(role_exercise, REPS)], title="Роль внутри Builder")
    body = await _start(session, user, plan_item_id)
    await _complete(session, user, body["id"])

    response = await v2_delete(session, telegram_id=user.telegram_id, path=f"/api/v2/sessions/{body['id']}")
    assert response.status_code == 409
