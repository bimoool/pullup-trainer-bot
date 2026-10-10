"""#306 B1 (приёмка) — офлайн-очередь движка v2 и повторное открытие приложения, на реальном Postgres.

Клиент (App, webapp-frontend/src/liveEngineClient.ts::drainEngineQueues) досылает сохранённые события ДО
любого запроса, способного спроецировать дедлайны (GET /sessions/live/active, список сессий). Здесь —
серверная половина контракта: очередь, пришедшая первой, применяется со своим (зажатым) временем, хотя
дедлайн к моменту приёма уже прошёл; та же очередь ПОСЛЕ проекции — устаревший no-op (это и был баг B1:
подход на время записывался целью, пауза терялась). Семантика сервера не меняется."""

import pytest
from sqlalchemy import func, select

from app.db.models_program import SetLog, TrainingSession
from app.db.repositories.training_sessions import TrainingSessionRepository
from app.domain import live_engine as engine
from app.services import live_engine as live_engine_service
from app.services.live_engine import from_ms
from tests.test_web._v2_client import v2_get, v2_post
from tests.test_web.test_v2_live_engine import (
    LIVE,
    Clock,
    INTERVAL_3x,
    REPS_1x5,
    TIME_2x20_R10,
    _active,
    _assert_rebuild,
    _builder,
    _event,
    _post_events,
    _start,
    _state,
    _submit,
)
from tests.test_web.test_v2_live_session import _setup_step_session
from tests.test_web.test_v2_live_session_workout_start import _user


@pytest.fixture
def clock(monkeypatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(live_engine_service, "_utcnow", fake)
    return fake


TIME_1x60 = {
    "type": "time_sets",
    "rest_seconds": 10,
    "prescription": {"source": "static", "sets": 1, "duration_seconds": 60},
}


async def _set_log_values(session, session_id: int) -> list[str]:
    rows = await session.execute(
        select(SetLog.value).where(SetLog.session_id == session_id).order_by(SetLog.set_index)
    )
    return [str(v) for v in rows.scalars().all()]


async def _timed_session_at_work(session, clock, telegram_id: int):
    user = await _user(session, telegram_id)
    workout = await _builder(session, user, [TIME_1x60, REPS_1x5])
    body = await _start(session, user, clock, workout_id=workout.id)
    t0 = _state(body)["started_at"]
    clock.ms = t0 + 5_000 + 1  # PREP 5 с позади — идёт подход 60 с
    state = _state(await _active(session, user))
    assert state["phase"] == "WORK" and state["phase_deadline_at"] == t0 + 65_000
    return user, body, state


async def test_offline_early_stop_drained_before_projection_keeps_measured_value(session, clock):
    """Стоп в 20 с (офлайн), приложение открыто через 5 мин: очередь досылается первой — 20 с, не 60."""
    user, body, work = await _timed_session_at_work(session, clock, 306301)
    stop = _event("stop", {"phase_seq": work["phase_seq"]}, at=work["phase_started_at"] + 20_000)
    clock.ms = (
        work["phase_started_at"] + 300_000
    )  # дедлайн подхода давно прошёл, проекции ещё не было
    drained = await _post_events(session, user, body["id"], stop)  # App: досылка до GET /active
    assert drained["event_results"][0]["outcome"] == "applied"
    assert [log["value"] for log in _state(drained)["logs"]] == [20]
    assert await _set_log_values(session, body["id"]) == ["20.00"]
    resumed = _state(await _active(session, user))  # затем — авторитетное состояние
    assert resumed["phase"] == "WORK" and resumed["cursor"]["block_index"] == 1
    retry = await _post_events(session, user, body["id"], stop)  # потерянный ответ досылки — повтор
    assert retry["event_results"][0]["outcome"] == "duplicate"
    assert await _set_log_values(session, body["id"]) == ["20.00"]
    await _assert_rebuild(session, body["id"])


async def test_same_offline_stop_after_projection_is_stale_which_is_why_drain_goes_first(
    session, clock
):
    """Обратный порядок (GET /active раньше очереди — баг B1): проекция уже записала цель, Стоп — no-op.
    Сервер здесь прав (дедлайн — авторитет, client_at зажат); порядок обязан обеспечить клиент."""
    user, body, work = await _timed_session_at_work(session, clock, 306302)
    stop = _event("stop", {"phase_seq": work["phase_seq"]}, at=work["phase_started_at"] + 20_000)
    clock.ms = work["phase_started_at"] + 300_000
    await _active(session, user)
    late = await _post_events(session, user, body["id"], stop)
    assert late["event_results"][0]["outcome"] == "noop"
    assert await _set_log_values(session, body["id"]) == ["60.00"]


async def test_offline_pause_drained_before_projection_stays_paused_with_exact_remaining(
    session, clock
):
    """Пауза интервала (офлайн), приложение открыто через 10 мин: досылка первой — пауза, остаток точный,
    тренировка не завершилась сама; второе устройство видит паузу."""
    user = await _user(session, 306303)
    workout = await _builder(session, user, [INTERVAL_3x])
    body = await _start(session, user, clock, workout_id=workout.id)
    t0 = _state(body)["started_at"]
    clock.ms = t0 + 6_000
    work = _state(await _active(session, user))
    assert work["phase"] == "WORK" and work["phase_deadline_at"] == t0 + 15_000
    pause = _event("pause", {"phase_seq": work["phase_seq"]}, at=t0 + 7_000)
    clock.ms = t0 + 600_000  # без паузы весь интервал (95 с) давно закончился бы
    drained = _state(await _post_events(session, user, body["id"], pause))
    assert drained["status"] == "active" and drained["paused_at"] == t0 + 7_000
    assert drained["paused_remaining_ms"] == 8_000 and drained["phase_deadline_at"] is None
    other_device = _state(await _active(session, user))
    assert other_device["paused_at"] == t0 + 7_000 and other_device["paused_remaining_ms"] == 8_000
    row = await session.get(TrainingSession, body["id"])
    await session.refresh(row)
    assert row.completed_at is None
    await _assert_rebuild(session, body["id"])


async def test_queued_review_after_server_auto_completion_is_saved(session, clock):
    """Сервер завершил тренировку сам (GET /active → null); оценка/заметка из очереди досылаются
    идемпотентным complete — без второй прогрессии и без смены длительности."""
    user = await _user(session, 306304)
    workout = await _builder(session, user, [TIME_2x20_R10])
    body = await _start(session, user, clock, workout_id=workout.id)
    clock.ms = _state(body)["started_at"] + 200_000
    assert await _active(session, user) is None
    detail = await TrainingSessionRepository(session).get_for_user(body["id"], user.id)
    assert detail.status.value == "completed" and detail.effort is None
    duration = detail.duration_seconds
    for _ in range(2):  # повтор после потерянного ответа — тот же итог
        response = await v2_post(
            session,
            user.telegram_id,
            f"{LIVE}/{body['id']}/complete",
            {"abandoned": False, "effort": 4, "comment": "тяжело"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["progression_skipped_reason"] == "already_completed"
    detail = await TrainingSessionRepository(session).get_for_user(body["id"], user.id)
    assert (
        str(detail.effort) == "4.0"
        and detail.comment == "тяжело"
        and detail.duration_seconds == duration
    )
    journal = (await v2_get(session, user.telegram_id, "/api/v2/sessions")).json()["sessions"]
    assert [card["id"] for card in journal].count(body["id"]) == 1


async def test_redrained_completing_queue_never_duplicates_sets_completion_or_credit(
    session, clock
):
    """Очередь с последним подходом курса (завершение) досылается дважды (ответ потерян): дубль — no-op,
    без второго SetLog, второго завершения, кредита и прогрессии."""
    user = await _user(session, 306305)
    _, _, plan_item_ids = await _setup_step_session(session, user)
    body = await _start(
        session, user, clock, plan_item_ids=[plan_item_ids["block_a"], plan_item_ids["block_b"]]
    )
    queue = []
    t = _state(body)["started_at"]
    state = _state(body)
    plan = body["engine"]["plan"]
    for _ in range(4):  # офлайн: подходы считаются той же функцией переходов, что у клиента
        state, _, _ = engine.project(plan, state, t)
        if state["phase"] != "WORK":
            t = state["phase_deadline_at"]
            state, _, _ = engine.project(plan, state, t)
        t += 3_000
        event = _submit(state, 12)
        event["client_at"] = from_ms(t).isoformat()
        queue.append(event)
        state, _, _ = engine.apply_event(
            plan, state, {"type": event["type"], "payload": event["payload"]}, t
        )
    assert state["status"] == "completed"
    clock.ms = t + 60_000
    first = await _post_events(session, user, body["id"], *queue)
    assert [r["outcome"] for r in first["event_results"]] == ["applied"] * 4 and first[
        "status"
    ] == "completed"
    assert first["progression_result"] is not None
    second = await _post_events(session, user, body["id"], *queue)
    assert [r["outcome"] for r in second["event_results"]] == ["duplicate"] * 4 and second[
        "progression_result"
    ] is None
    count = await session.scalar(
        select(func.count(SetLog.id)).where(SetLog.session_id == body["id"])
    )
    assert count == 4
    repo = TrainingSessionRepository(session)
    detail = await repo.get_for_user(body["id"], user.id)
    assert len(await repo.credits_for_plan_items([detail.plan_item_id])) == 1
    await _assert_rebuild(session, body["id"])
