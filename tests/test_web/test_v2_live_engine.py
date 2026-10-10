"""Live Engine v2 (issue #306, docs/domain/LIVE_ENGINE_V2.md) — приёмка A–T через API на реальном Postgres.

Часы движка детерминированы: ``app.services.live_engine._utcnow`` подменяется (фикстура ``clock``), отсчёт
ведётся от ``state.started_at`` самой сессии. Буквы — из постановки #306 (раздел 19)."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.models_program import (
    Complex,
    ComplexItem,
    Exercise,
    SessionEvent,
    SetLog,
    TrainingSession,
)
from app.db.repositories.training_sessions import TrainingSessionRepository
from app.domain.multi_program import MetricType
from app.services import live_engine as live_engine_service
from app.services.live_engine import LiveEngineService, from_ms
from app.services.workout_definition import WorkoutDefinitionService
from tests.test_web._v2_client import v2_get, v2_post
from tests.test_web.test_v2_live_session import _setup_step_session
from tests.test_web.test_v2_live_session_workout_start import _user

LIVE = "/api/v2/sessions/live"
REPS_2x8_R30 = {"type": "reps_sets", "rest_seconds": 30, "prescription": {"source": "static", "sets": 2, "reps": 8}}
REPS_1x5 = {"type": "reps_sets", "rest_seconds": 0, "prescription": {"source": "static", "sets": 1, "reps": 5}}
TIME_2x20_R10 = {"type": "time_sets", "rest_seconds": 10, "prescription": {"source": "static", "sets": 2, "duration_seconds": 20}}
INTERVAL_3x = {"type": "interval", "total_duration_seconds": 90, "work_seconds": 10, "rest_seconds": 20, "starts_with": "work"}


class Clock:
    def __init__(self) -> None:
        self.ms: int | None = None

    def __call__(self) -> datetime:
        return from_ms(self.ms) if self.ms is not None else datetime.now(UTC)


@pytest.fixture
def clock(monkeypatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(live_engine_service, "_utcnow", fake)
    return fake


async def _builder(session: AsyncSession, owner: User, protocols: list[dict], *, title: str = "Движок v2") -> Complex:
    """Builder-тренировка с версией определения v2 (как после правки в Builder: sync_head)."""
    workout = Complex(name=title, source_type="user", owner_user_id=owner.id)
    session.add(workout)
    await session.flush()
    for index, protocol in enumerate(protocols):
        metric = MetricType.TIME if protocol["type"] == "time_sets" else MetricType.REPS
        exercise = Exercise(name=f"Упражнение {index + 1}", metric_type=metric, category="engine-v2")
        session.add(exercise)
        await session.flush()
        session.add(ComplexItem(complex_id=workout.id, exercise_id=exercise.id, order_index=index, sets=1, protocol=protocol))
    await session.flush()
    await WorkoutDefinitionService(session).sync_head(workout.id)
    return workout


async def _start(session, user: User, clock: Clock, **payload) -> dict:
    body = {"client_session_id": str(uuid.uuid4()), "engine_version": 2, **payload}
    response = await v2_post(session, user.telegram_id, LIVE, body)
    assert response.status_code == 200, response.text
    data = response.json()
    clock.ms = data["engine"]["state"]["started_at"]
    return data


def _event(type_: str, payload: dict | None = None, *, at: int | None = None, cid: str | None = None) -> dict:
    event = {"client_event_id": cid or str(uuid.uuid4()), "type": type_, "payload": payload or {}}
    if at is not None:
        event["client_at"] = from_ms(at).isoformat()
    return event


async def _post_events(session, user: User, session_id: int, *events: dict, status: int = 200) -> dict:
    response = await v2_post(session, user.telegram_id, f"{LIVE}/{session_id}/events", {"events": list(events)})
    assert response.status_code == status, response.text
    return response.json()


async def _active(session, user: User) -> dict | None:
    response = await v2_get(session, user.telegram_id, f"{LIVE}/active")
    assert response.status_code == 200, response.text
    return response.json()["session"]


def _state(body: dict) -> dict:
    return body["engine"]["state"]


def _submit(state: dict, value: int, **extra) -> dict:
    cursor = state["cursor"]
    return _event("submit_result", {
        "block_index": cursor["block_index"], "set_index": cursor["set_index"], "round_index": cursor["round_index"],
        "value": value, **extra,
    })


async def _set_logs(session: AsyncSession, session_id: int) -> list[SetLog]:
    rows = await session.execute(select(SetLog).where(SetLog.session_id == session_id).order_by(SetLog.set_index))
    return list(rows.scalars().all())


async def _event_count(session: AsyncSession, session_id: int) -> int:
    return await session.scalar(select(func.count(SessionEvent.id)).where(SessionEvent.session_id == session_id))


async def _assert_rebuild(session: AsyncSession, session_id: int) -> None:
    """L: свёртка session_events == сохранённое engine_state."""
    stored = await session.scalar(select(TrainingSession.engine_state).where(TrainingSession.id == session_id))
    assert await LiveEngineService(session).rebuild_state(session_id) == stored


# --- A, B, D, E: авто-переходы и фон --------------------------------------------------------


async def test_a_prep_reaches_work_at_the_deadline_without_a_tap(session, clock):
    user = await _user(session, 306001)
    workout = await _builder(session, user, [REPS_2x8_R30])
    body = await _start(session, user, clock, workout_id=workout.id)
    assert body["engine_version"] == 2
    state = _state(body)
    t0 = state["started_at"]
    assert state["phase"] == "PREP" and state["phase_deadline_at"] == t0 + 5000
    clock.ms = t0 + 4999
    assert _state(await _active(session, user))["phase"] == "PREP"
    clock.ms = t0 + 5000
    state = _state(await _active(session, user))
    assert state["phase"] == "WORK" and state["phase_started_at"] == t0 + 5000  # A: без тапа
    rows = await session.execute(select(SessionEvent.type, SessionEvent.server_at).where(SessionEvent.session_id == body["id"]))
    assert [(t, at) for t, at in rows.all()] == [("start", from_ms(t0)), ("deadline", from_ms(t0 + 5000))]
    await _assert_rebuild(session, body["id"])


async def test_b_d_e_rest_ends_in_background_next_set_is_already_work(session, clock):
    """B + D + E: отдых закончился, пока приложение было в фоне 60 с — на возврате уже WORK
    следующего подхода, отсчёт по серверу (deadline − server_time) точен до секунды."""
    user = await _user(session, 306002)
    workout = await _builder(session, user, [REPS_2x8_R30])
    body = await _start(session, user, clock, workout_id=workout.id)
    t0 = _state(body)["started_at"]
    clock.ms = t0 + 10_000
    body = await _post_events(session, user, body["id"], _submit(_state(await _active(session, user)), 8))
    state = _state(body)
    assert state["phase"] == "REST" and state["phase_deadline_at"] == t0 + 40_000
    remaining = state["phase_deadline_at"] - body["engine"]["server_time_ms"]
    assert abs(remaining - 30_000) <= 1000  # E
    clock.ms = t0 + 70_000  # фон 60 с поперёк конца отдыха
    returned = await _active(session, user)
    state = _state(returned)
    assert state["phase"] == "WORK" and state["cursor"]["set_index"] == 1  # D: без тапа
    assert state["phase_started_at"] == t0 + 40_000
    assert [cue for cue in returned["engine"]["timeline"] if cue["at"] < clock.ms] == [
        {"type": "work_start", "at": t0 + 40_000},
    ]  # P4: прошедшее — только как факт; UI его не проигрывает
    await _assert_rebuild(session, body["id"])


async def test_c_block_rest_then_next_block_starts_automatically(session, clock):
    user = await _user(session, 306003)
    workout = await _builder(session, user, [REPS_1x5, TIME_2x20_R10])
    body = await _start(session, user, clock, workout_id=workout.id)
    plan = body["engine"]["plan"]
    t0 = _state(body)["started_at"]
    block_rest = plan["blocks"][0]["rest_after_block_seconds"]
    prep_b = plan["blocks"][1]["prep_seconds"]
    assert block_rest and block_rest > 0 and prep_b == 5  # §3.6: блок на время — 5 с подготовки
    clock.ms = t0 + 9_000
    body = await _post_events(session, user, body["id"], _submit(_state(await _active(session, user)), 5))
    state = _state(body)
    assert state["phase"] == "REST" and state["rest_kind"] == "block"
    block_end = t0 + 9_000 + block_rest * 1000
    clock.ms = block_end + prep_b * 1000 + 1
    state = _state(await _active(session, user))
    assert state["phase"] == "WORK" and state["cursor"]["block_index"] == 1  # без «Начать»
    clock.ms = block_end + prep_b * 1000 + 20_000 + 10_000 + 20_000  # оба подхода на время — сами
    final = await _active(session, user)
    assert final is None  # завершена сервером, «нечего продолжать»
    detail = await TrainingSessionRepository(session).get_for_user(body["id"], user.id)
    assert detail.status.value == "completed" and detail.duration_source == "measured"
    assert [str(log.value) for log in detail.blocks[1].set_logs] == ["20.00", "20.00"]
    started = await session.scalar(select(TrainingSession.started_at).where(TrainingSession.id == body["id"]))
    assert detail.ended_at == from_ms(block_end + prep_b * 1000 + 50_000) and detail.ended_at > started
    await _assert_rebuild(session, body["id"])


# --- F, G, H: пауза на сервере ---------------------------------------------------------------


async def test_f_g_h_pause_survives_reload_and_second_device_resume_keeps_remaining(session, clock):
    user = await _user(session, 306004)
    workout = await _builder(session, user, [REPS_2x8_R30])
    body = await _start(session, user, clock, workout_id=workout.id)
    t0 = _state(body)["started_at"]
    clock.ms = t0 + 10_000
    state = _state(await _post_events(session, user, body["id"], _submit(_state(await _active(session, user)), 8)))
    clock.ms = t0 + 20_000  # 20 с из 30 отдыха осталось
    paused = _state(await _post_events(session, user, body["id"], _event("pause", {"phase_seq": state["phase_seq"]})))
    assert paused["paused_remaining_ms"] == 20_000 and paused["phase_deadline_at"] is None
    clock.ms = t0 + 500_000  # «устройство B» открывает сессию много позже: пауза на сервере
    other_device = _state(await _active(session, user))
    assert other_device["phase"] == "REST" and other_device["paused_at"] == t0 + 20_000  # F + G
    resumed = _state(await _post_events(session, user, body["id"], _event("resume", {"phase_seq": state["phase_seq"]})))
    assert resumed["phase_deadline_at"] == t0 + 520_000  # H: тот же остаток 20 с
    detail = await TrainingSessionRepository(session).get_for_user(body["id"], user.id)
    assert detail.phase_ends_at == from_ms(t0 + 520_000)  # зеркало колонок v1
    await _assert_rebuild(session, body["id"])


# --- I, J, K, L: идемпотентность, устаревшие события, офлайн-повтор ---------------------------


async def test_i_duplicate_client_event_is_a_200_noop(session, clock):
    user = await _user(session, 306005)
    workout = await _builder(session, user, [REPS_2x8_R30])
    body = await _start(session, user, clock, workout_id=workout.id)
    clock.ms = _state(body)["started_at"] + 10_000
    event = _submit(_state(await _active(session, user)), 8)
    first = await _post_events(session, user, body["id"], event)
    events_after_first = await _event_count(session, body["id"])
    second = await _post_events(session, user, body["id"], event)  # потерянный ответ + повтор
    assert first["event_results"][0]["outcome"] == "applied"
    assert second["event_results"][0]["outcome"] == "duplicate"
    assert _state(second) == _state(first)
    assert len(await _set_logs(session, body["id"])) == 1
    assert await _event_count(session, body["id"]) == events_after_first


async def test_i_client_event_id_of_another_session_is_422(session, clock):
    user = await _user(session, 306006)
    other = await _user(session, 306007)
    workout = await _builder(session, user, [REPS_2x8_R30])
    workout_b = await _builder(session, other, [REPS_2x8_R30])
    mine = await _start(session, user, clock, workout_id=workout.id)
    theirs = await _start(session, other, clock, workout_id=workout_b.id)
    event = _event("pause", {"phase_seq": 0})
    await _post_events(session, user, mine["id"], event)
    await _post_events(session, other, theirs["id"], event, status=422)
    await _post_events(session, other, mine["id"], _event("pause", {"phase_seq": 0}), status=404)  # чужая — 404


async def test_j_offline_pause_before_the_deadline_still_applies(session, clock):
    """Контрпара J: пауза, поставленная офлайн ДО дедлайна (сервер ещё не проецировал), применяется со
    своим client_at — пауза не теряется из-за позднего реконнекта."""
    user = await _user(session, 306023)
    workout = await _builder(session, user, [REPS_2x8_R30])
    body = await _start(session, user, clock, workout_id=workout.id)
    t0 = _state(body)["started_at"]
    clock.ms = t0 + 60_000
    result = await _post_events(session, user, body["id"], _event("pause", {"phase_seq": 0}, at=t0 + 2000))
    assert result["event_results"][0]["outcome"] == "applied"
    assert _state(result)["phase"] == "PREP" and _state(result)["paused_remaining_ms"] == 3000


async def test_j_stale_event_after_server_advanced_is_a_noop(session, clock):
    user = await _user(session, 306008)
    workout = await _builder(session, user, [REPS_2x8_R30])
    body = await _start(session, user, clock, workout_id=workout.id)
    t0 = _state(body)["started_at"]
    clock.ms = t0 + 6000
    assert _state(await _active(session, user))["phase"] == "WORK"  # сервер уже перешёл (дедлайн записан)
    stale = await _post_events(session, user, body["id"], _event("pause", {"phase_seq": 0}, at=t0 + 2000))
    assert stale["event_results"][0]["outcome"] == "noop"
    assert _state(stale)["phase"] == "WORK" and _state(stale)["paused_at"] is None


async def test_k_l_offline_queue_replays_deterministically_and_rebuilds(session, clock):
    """K: очередь, накопленная офлайн (подход, отдых истёк, подход, пауза), уходит одним запросом после
    реконнекта — результат тот же, что при онлайне; L: свёртка журнала = сохранённое состояние."""
    user = await _user(session, 306009)
    workout = await _builder(session, user, [REPS_2x8_R30, REPS_1x5])
    body = await _start(session, user, clock, workout_id=workout.id)
    t0 = _state(body)["started_at"]
    queue = [
        _event("submit_result", {"block_index": 0, "set_index": 0, "round_index": None, "value": 8}, at=t0 + 9_000),
        _event("submit_result", {"block_index": 0, "set_index": 1, "round_index": None, "value": 7}, at=t0 + 50_000),
        _event("pause", {"phase_seq": 4}, at=t0 + 55_000),
    ]
    clock.ms = t0 + 300_000
    result = await _post_events(session, user, body["id"], *queue)
    assert [r["outcome"] for r in result["event_results"]] == ["applied", "applied", "applied"]
    state = _state(result)
    assert state["phase"] == "REST" and state["rest_kind"] == "block" and state["paused_at"] == t0 + 55_000
    logs = await _set_logs(session, body["id"])
    assert [(log.set_number, str(log.value)) for log in logs] == [(1, "8.00"), (2, "7.00")]
    types = (await session.execute(
        select(SessionEvent.type).where(SessionEvent.session_id == body["id"]).order_by(SessionEvent.seq),
    )).scalars().all()
    assert types == ["start", "deadline", "submit_result", "deadline", "submit_result", "pause"]
    retry = await _post_events(session, user, body["id"], *queue)  # вся очередь ещё раз (потерянный ответ)
    assert [r["outcome"] for r in retry["event_results"]] == ["duplicate"] * 3
    assert _state(retry) == state
    await _assert_rebuild(session, body["id"])


async def test_k_untrusted_client_at_is_clamped(session, clock):
    user = await _user(session, 306010)
    workout = await _builder(session, user, [REPS_2x8_R30])
    body = await _start(session, user, clock, workout_id=workout.id)
    t0 = _state(body)["started_at"]
    clock.ms = t0 + 7000
    future = _event("submit_result", {"block_index": 0, "set_index": 0, "round_index": None, "value": 8}, at=t0 + 10**9)
    state = _state(await _post_events(session, user, body["id"], future))
    assert state["logs"][0]["logged_at"] == t0 + 7000  # «будущее» клиента — не позже сервера
    past = _event("correct_previous", {"block_index": 0, "set_index": 0, "round_index": None, "value": 9}, at=t0 - 10**9)
    state = _state(await _post_events(session, user, body["id"], past))
    assert state["last_at"] >= t0 + 7000  # время движка не идёт назад


# --- M: интервал на том же движке ----------------------------------------------------------


async def test_m_interval_runs_on_the_same_engine_with_pause(session, clock):
    user = await _user(session, 306011)
    workout = await _builder(session, user, [INTERVAL_3x])
    body = await _start(session, user, clock, workout_id=workout.id)
    plan = body["engine"]["plan"]
    assert plan["blocks"][0]["kind"] == "interval" and plan["blocks"][0]["interval"]["rounds"] == 3
    t0 = _state(body)["started_at"]
    clock.ms = t0 + 5_000 + 30_000 + 2_000  # раунд 2 идёт, 8 с работы осталось
    state = _state(await _active(session, user))
    assert state["phase"] == "WORK" and state["cursor"]["round_index"] == 1
    paused = _state(await _post_events(session, user, body["id"], _event("pause", {"phase_seq": state["phase_seq"]})))
    assert paused["paused_remaining_ms"] == 8_000
    clock.ms += 60_000
    assert _state(await _active(session, user))["paused_at"] is not None
    await _post_events(session, user, body["id"], _event("resume", {"phase_seq": state["phase_seq"]}))
    clock.ms += 8_000 + 20_000 + 30_000
    assert await _active(session, user) is None  # три раунда — завершена сама
    detail = await TrainingSessionRepository(session).get_for_user(body["id"], user.id)
    assert detail.status.value == "completed"
    assert detail.blocks[0].result["type"] == "interval" and detail.blocks[0].result["completed_cycles"] == 3
    assert detail.duration_seconds == 95  # 5 + 3 × 30 активных секунд, пауза 60 с исключена
    await _assert_rebuild(session, body["id"])


# --- N, O: ещё подход и правка ---------------------------------------------------------------


async def test_n_o_extra_set_and_correct_previous(session, clock):
    user = await _user(session, 306012)
    workout = await _builder(session, user, [REPS_1x5, REPS_1x5])
    body = await _start(session, user, clock, workout_id=workout.id)
    t0 = _state(body)["started_at"]
    clock.ms = t0 + 9_000
    state = _state(await _post_events(session, user, body["id"], _submit(_state(await _active(session, user)), 5)))
    assert state["phase"] == "REST" and state["rest_kind"] == "block"
    seq = state["phase_seq"]
    state = _state(await _post_events(
        session, user, body["id"],
        _event("add_extra_set", {"block_index": 0, "value": 3}),
        _event("correct_previous", {"block_index": 0, "set_index": 0, "round_index": None, "value": 6}),
    ))
    assert state["phase"] == "REST" and state["phase_seq"] == seq  # фаза не тронута
    logs = await _set_logs(session, body["id"])
    assert [(str(log.value), log.is_extra) for log in logs] == [("6.00", False), ("3.00", True)]
    assert logs[0].set_target_id is not None and logs[1].set_target_id is None
    await _assert_rebuild(session, body["id"])


async def test_o_correction_after_completion_bumps_revision(session, clock):
    user = await _user(session, 306013)
    workout = await _builder(session, user, [REPS_1x5])
    body = await _start(session, user, clock, workout_id=workout.id)
    clock.ms = _state(body)["started_at"] + 9_000
    done = await _post_events(session, user, body["id"], _submit(_state(await _active(session, user)), 5))
    assert done["status"] == "completed"
    revision = await session.scalar(select(TrainingSession.revision).where(TrainingSession.id == body["id"]))
    await _post_events(session, user, body["id"], _event("correct_previous", {
        "block_index": 0, "set_index": 0, "round_index": None, "value": 7,
    }))
    row = await session.get(TrainingSession, body["id"])
    await session.refresh(row)
    assert row.revision == revision + 1 and row.status.value == "completed"
    assert [str(log.value) for log in await _set_logs(session, body["id"])] == ["7.00"]


# --- P, Q: досрочно и отмена ------------------------------------------------------------------


async def test_p_finish_early_is_a_valid_completed_session(session, clock):
    user = await _user(session, 306014)
    workout = await _builder(session, user, [REPS_2x8_R30])
    body = await _start(session, user, clock, workout_id=workout.id)
    t0 = _state(body)["started_at"]
    clock.ms = t0 + 9_000
    await _post_events(session, user, body["id"], _submit(_state(await _active(session, user)), 8))
    clock.ms = t0 + 20_000
    result = await _post_events(session, user, body["id"], _event("finish_early"))
    assert result["status"] == "completed" and _state(result)["status"] == "completed"
    assert result["progression_skipped_reason"] == "abandoned"  # #307: досрочно — прогрессия пропущена
    sessions = (await v2_get(session, user.telegram_id, "/api/v2/sessions?status=completed")).json()["sessions"]
    card = next(c for c in sessions if c["id"] == body["id"])
    outcomes = [o["status"] for o in card["blocks"][0]["outcomes"]]
    assert outcomes == ["performed", "not_performed"]
    assert card["duration_seconds"] == 20  # активное время движка
    assert card["title"] == "Движок v2"


async def test_q_cancel_leaves_no_journal_no_credit_and_frees_the_slot(session, clock):
    user = await _user(session, 306015)
    workout = await _builder(session, user, [REPS_2x8_R30])
    body = await _start(session, user, clock, workout_id=workout.id)
    clock.ms = _state(body)["started_at"] + 9_000
    await _post_events(session, user, body["id"], _submit(_state(await _active(session, user)), 8))
    result = await _post_events(session, user, body["id"], _event("cancel"))
    assert result["engine_status"] == "cancelled" and result["status"] == "started"
    assert await _active(session, user) is None
    journal = (await v2_get(session, user.telegram_id, "/api/v2/sessions")).json()["sessions"]
    assert body["id"] not in [c["id"] for c in journal]
    row = await session.get(TrainingSession, body["id"])
    assert row is not None and row.completed_at is None  # архив, не удалена и не завершена
    again = await _start(session, user, clock, workout_id=workout.id)  # слот свободен
    assert again["id"] != body["id"]


async def test_q_cancel_of_a_planned_session_releases_the_occurrence_credit(session, clock):
    user = await _user(session, 306016)
    _, _, plan_item_ids = await _setup_step_session(session, user)
    body = await _start(session, user, clock, plan_item_ids=[plan_item_ids["block_a"], plan_item_ids["block_b"]])
    repo = TrainingSessionRepository(session)
    credited = (await repo.get_for_user(body["id"], user.id)).plan_item_id
    assert credited is not None
    await _post_events(session, user, body["id"], _event("cancel"))
    assert (await repo.get_for_user(body["id"], user.id)).plan_item_id is None
    assert await repo.credits_for_plan_items([credited]) == []


async def test_q_zero_work_finish_through_complete_endpoint_is_a_cancel(session, clock):
    user = await _user(session, 306017)
    workout = await _builder(session, user, [REPS_2x8_R30])
    body = await _start(session, user, clock, workout_id=workout.id)
    clock.ms = _state(body)["started_at"] + 60_000
    response = await v2_post(session, user.telegram_id, f"{LIVE}/{body['id']}/complete", {"abandoned": True, "effort": 3})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["progression_skipped_reason"] == "cancelled" and data["status"] == "started"
    row = await session.get(TrainingSession, body["id"])
    await session.refresh(row)
    assert row.duration_seconds is None and row.effort is None and row.engine_status == "cancelled"


# --- R, S: совместимость движков -------------------------------------------------------------


async def test_r_engine_v1_session_still_completes_on_the_old_path(session, clock):
    user = await _user(session, 306018)
    workout = await _builder(session, user, [REPS_2x8_R30])
    response = await v2_post(session, user.telegram_id, LIVE, {"client_session_id": str(uuid.uuid4()), "workout_id": workout.id})
    v1 = response.json()
    assert v1["engine_version"] == 1 and v1["engine"] is None and v1["phase"]["name"] == "get_ready"
    advanced = await v2_post(session, user.telegram_id, f"{LIVE}/{v1['id']}/phase/next", {"expected_phase_index": 0})
    assert advanced.status_code == 200 and advanced.json()["phase"]["name"] == "go"
    events = await v2_post(session, user.telegram_id, f"{LIVE}/{v1['id']}/events", {"events": [_event("pause", {"phase_seq": 0})]})
    assert events.status_code == 409 and events.json()["detail"]["code"] == "engine_version_mismatch"
    done = await v2_post(session, user.telegram_id, f"{LIVE}/{v1['id']}/complete", {"abandoned": False})
    assert done.status_code == 200 and done.json()["status"] == "completed"
    row = await session.get(TrainingSession, v1["id"])
    assert row.engine_version == 1 and row.engine_state is None
    assert await _event_count(session, v1["id"]) == 0


async def test_s_engine_v2_session_rejects_every_v1_transition_endpoint(session, clock):
    user = await _user(session, 306019)
    workout = await _builder(session, user, [REPS_2x8_R30])
    body = await _start(session, user, clock, workout_id=workout.id)
    before = _state(await _active(session, user))
    for path, payload in (
        ("phase/next", {"expected_phase_index": 0}), ("phase/back", {"expected_phase_index": 0}),
        ("blocks/start", {"expected_block_index": 1}), ("blocks/finish", {"expected_block_index": 0}),
        ("sets:batch", {"sets": [{"set_index": 0, "exercise_id": body["blocks"][0]["exercise_id"], "value": "8"}]}),
    ):
        response = await v2_post(session, user.telegram_id, f"{LIVE}/{body['id']}/{path}", payload)
        assert response.status_code == 409, path
        assert response.json()["detail"]["code"] == "engine_version_mismatch"
    assert _state(await _active(session, user)) == before
    assert await _set_logs(session, body["id"]) == []


# --- T: повтор завершения ---------------------------------------------------------------------


async def test_t_completion_retry_never_duplicates_progression_or_credit(session, clock):
    """Курс (STEP): прогрессия применяется ровно один раз; повторы (complete, события после
    завершения) — already_completed, без второго кредита и без смены длительности."""
    user = await _user(session, 306020)
    inclusion, _, plan_item_ids = await _setup_step_session(session, user)
    body = await _start(session, user, clock, plan_item_ids=[plan_item_ids["block_a"], plan_item_ids["block_b"]])
    assert body["engine_version"] == 2
    plan = body["engine"]["plan"]
    assert [len(b["sets"]) for b in plan["blocks"]] == [3, 1]  # цели курса (progression_state), #305 не трогаем
    t = _state(body)["started_at"]
    for _ in range(4):
        state = _state(await _active(session, user))
        if state["phase"] != "WORK":
            t = state["phase_deadline_at"]
            clock.ms = t
            state = _state(await _active(session, user))
        t += 3_000
        clock.ms = t
        last = await _post_events(session, user, body["id"], _submit(state, 12))
    assert last["status"] == "completed"
    assert last["progression_result"] is not None and last["progression_skipped_reason"] is None
    repo = TrainingSessionRepository(session)
    duration = (await repo.get_for_user(body["id"], user.id)).duration_seconds
    rev = await session.scalar(
        select(TrainingSession.id).where(TrainingSession.id == body["id"]),
    )
    assert rev == body["id"]
    retry = await v2_post(session, user.telegram_id, f"{LIVE}/{body['id']}/complete", {"abandoned": False, "effort": 4})
    assert retry.status_code == 200
    assert retry.json()["progression_skipped_reason"] == "already_completed"
    again = await _post_events(session, user, body["id"], _event("finish_early"))
    assert again["event_results"][0]["outcome"] == "noop" and again["progression_result"] is None
    detail = await repo.get_for_user(body["id"], user.id)
    assert detail.duration_seconds == duration and str(detail.effort) == "4.0"
    assert len(await repo.credits_for_plan_items([detail.plan_item_id])) == 1
    from app.db.models_program import ProgramInclusion

    row = await session.get(ProgramInclusion, inclusion["id"])
    await session.refresh(row)
    assert row.progression_state_rev == 1  # ровно одна применённая прогрессия


# --- J3: лесенка исполняется как записана ---------------------------------------------------


async def test_w_ladder_executes_seventeen_sets_in_prescribed_order(session, clock):
    from tests.test_web.test_v2_workout_definition import _catalog, _ship_v2

    await _ship_v2(session)
    user = await _user(session, 306021)
    ladder = (await _catalog(session, user))["W-лесенка"]
    body = await _start(session, user, clock, workout_id=ladder["id"])
    targets = [int(float(t["value"])) for t in body["blocks"][0]["targets"]]
    assert targets == [5, 4, 3, 2, 1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5]
    sets = body["engine"]["plan"]["blocks"][0]["sets"]
    assert [s["target"] for s in sets] == targets and sets[0]["rest_after_seconds"] == 10 and sets[-1]["rest_after_seconds"] is None
    stored = await session.scalar(select(TrainingSession.prescription_snapshot).where(TrainingSession.id == body["id"]))
    assert stored["synthesized"] is False and stored["version_no"] == 2


async def test_rebuild_matches_after_a_full_mixed_session(session, clock):
    """L на смешанной тренировке: подходы → интервал → подходы, пауза, правка, ещё подход, финиш."""
    user = await _user(session, 306022)
    workout = await _builder(session, user, [REPS_1x5, INTERVAL_3x, REPS_2x8_R30])
    body = await _start(session, user, clock, workout_id=workout.id)
    clock.ms = _state(body)["started_at"] + 7_000
    sid = body["id"]
    await _post_events(session, user, sid, _submit(_state(await _active(session, user)), 5))
    await _post_events(session, user, sid, _event("add_extra_set", {"block_index": 0, "value": 2}))
    clock.ms += 400_000
    state = _state(await _active(session, user))
    assert state["cursor"]["block_index"] == 2 and state["phase"] == "WORK"
    await _post_events(session, user, sid, _submit(state, 8), _event("correct_previous", {
        "block_index": 0, "set_index": 0, "round_index": None, "value": 6,
    }))
    clock.ms += 10_000
    state = _state(await _active(session, user))
    await _post_events(session, user, sid, _event("pause", {"phase_seq": state["phase_seq"]}))
    clock.ms += 1_000
    await _post_events(session, user, sid, _event("finish_early"))
    await _assert_rebuild(session, sid)
    detail = await TrainingSessionRepository(session).get_for_user(sid, user.id)
    assert detail.status.value == "completed" and detail.blocks[1].result["completed_cycles"] == 3
