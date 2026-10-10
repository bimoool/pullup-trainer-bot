"""Live Engine v2 (issue #306) — гонки на реальном Postgres: каждый запрос — своя транзакция с коммитом
(как app.web.db.get_session), вход в LiveEngineService.sync синхронизирован барьером — оба запроса читают
состояние до того, как любой из них закоммитит. Порядок блокировок: строка training_sessions FOR UPDATE
(тот же, что у sets:batch/complete) — второй ждёт первого, дедлоков и дублей нет."""

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models_program import ProgramInclusion, SessionEvent, SetLog, TrainingSession
from app.services import live_engine as live_engine_service
from app.services.live_engine import LiveEngineService, from_ms
from app.web.main import app
from tests.test_web.test_v2_live_engine import (
    Clock,
    REPS_1x5,
    REPS_2x8_R30,
    _builder,
    _event,
    _start,
)
from tests.test_web.test_v2_live_session import _setup_step_session
from tests.test_web.test_v2_live_session_concurrency import _gate, _per_request_sessions
from tests.test_web.test_v2_live_session_workout_start import _user

LIVE = "/api/v2/sessions/live"
ROUNDS = 2


@pytest.fixture
def clock(monkeypatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(live_engine_service, "_utcnow", fake)
    return fake


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t")


async def _fresh(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)()


async def _invariants(engine, session_id: int) -> dict:
    """Журнал событий: seq непрерывен и уникален; свёртка == сохранённое состояние; без дублей подходов."""
    async with await _fresh(engine) as db:
        seqs = (await db.execute(
            select(SessionEvent.seq).where(SessionEvent.session_id == session_id).order_by(SessionEvent.seq),
        )).scalars().all()
        assert seqs == list(range(len(seqs)))
        stored = await db.scalar(select(TrainingSession.engine_state).where(TrainingSession.id == session_id))
        assert await LiveEngineService(db).rebuild_state(session_id) == stored
        logs = (await db.execute(select(SetLog.set_index).where(SetLog.session_id == session_id))).scalars().all()
        assert len(logs) == len(set(logs))
        deadlines = (await db.execute(
            select(SessionEvent.server_at).where(SessionEvent.session_id == session_id, SessionEvent.type == "deadline"),
        )).scalars().all()
        assert len(deadlines) == len(set(deadlines))  # проекция одного дедлайна записана один раз
        await db.rollback()
        return stored


async def _prepared(session, user_id: int, clock: Clock, protocols, **start) -> tuple:
    user = await _user(session, user_id)
    if "plan_item_ids" not in start:
        workout = await _builder(session, user, protocols)
        start = {"workout_id": workout.id}
    body = await _start(session, user, clock, **start)
    await session.commit()
    return user, body


@pytest.mark.parametrize("round_", range(ROUNDS))
async def test_two_devices_send_the_same_event(session, test_dsn, monkeypatch, clock, round_):
    user, body = await _prepared(session, 306100 + round_, clock, [REPS_2x8_R30])
    t0 = body["engine"]["state"]["started_at"]
    clock.ms = t0 + 9_000
    event = _event("submit_result", {"block_index": 0, "set_index": 0, "round_index": None, "value": 8})
    _gate(monkeypatch, LiveEngineService, "sync")
    with _per_request_sessions(test_dsn, user.telegram_id) as engine:
        async with _client() as c:
            a, b = await asyncio.gather(
                c.post(f"{LIVE}/{body['id']}/events", json={"events": [event]}),
                c.post(f"{LIVE}/{body['id']}/events", json={"events": [event]}),
            )
        assert (a.status_code, b.status_code) == (200, 200), (a.text, b.text)
        outcomes = sorted(r.json()["event_results"][0]["outcome"] for r in (a, b))
        assert outcomes == ["applied", "duplicate"]
        state = await _invariants(engine, body["id"])
        assert [log["value"] for log in state["logs"]] == [8]
        await engine.dispose()


@pytest.mark.parametrize("round_", range(ROUNDS))
async def test_two_devices_send_different_valid_events(session, test_dsn, monkeypatch, clock, round_):
    """A ставит паузу на отдыхе, B одновременно жмёт «Начать сейчас» (тот же phase_seq). Порядок решает
    блокировка: пауза → «Начать сейчас» (тот же seq, снимает паузу и начинает) — оба applied;
    «Начать сейчас» → пауза (seq уже другой) — пауза устаревшая, no-op. Итог один: WORK следующего подхода."""
    user, body = await _prepared(session, 306110 + round_, clock, [REPS_2x8_R30])
    t0 = body["engine"]["state"]["started_at"]
    clock.ms = t0 + 9_000
    first = _event("submit_result", {"block_index": 0, "set_index": 0, "round_index": None, "value": 8})
    with _per_request_sessions(test_dsn, user.telegram_id) as engine:
        async with _client() as c:
            rest = (await c.post(f"{LIVE}/{body['id']}/events", json={"events": [first]})).json()
        seq = rest["engine"]["state"]["phase_seq"]
        clock.ms = t0 + 20_000
        _gate(monkeypatch, LiveEngineService, "sync")
        async with _client() as c:
            a, b = await asyncio.gather(
                c.post(f"{LIVE}/{body['id']}/events", json={"events": [_event("pause", {"phase_seq": seq})]}),
                c.post(f"{LIVE}/{body['id']}/events", json={"events": [_event("skip_wait", {"phase_seq": seq})]}),
            )
        assert (a.status_code, b.status_code) == (200, 200), (a.text, b.text)
        state = await _invariants(engine, body["id"])
        assert state["phase"] == "WORK" and state["cursor"]["set_index"] == 1 and state["paused_at"] is None, state
        pause_outcome = a.json()["event_results"][0]["outcome"]
        assert b.json()["event_results"][0]["outcome"] == "applied" and pause_outcome in ("applied", "noop")
        await engine.dispose()


@pytest.mark.parametrize("round_", range(ROUNDS))
async def test_deadline_projection_races_a_user_event(session, test_dsn, monkeypatch, clock, round_):
    """Чтение после дедлайна (проекция пишет deadline) и событие пользователя одновременно: дедлайн
    записан ровно один раз, подход — один, свёртка совпадает."""
    user, body = await _prepared(session, 306120 + round_, clock, [REPS_2x8_R30])
    t0 = body["engine"]["state"]["started_at"]
    clock.ms = t0 + 9_000
    submit = _event("submit_result", {"block_index": 0, "set_index": 0, "round_index": None, "value": 8}, at=t0 + 9_000)
    _gate(monkeypatch, LiveEngineService, "sync")
    with _per_request_sessions(test_dsn, user.telegram_id) as engine:
        async with _client() as c:
            read, write = await asyncio.gather(
                c.get(f"{LIVE}/active"), c.post(f"{LIVE}/{body['id']}/events", json={"events": [submit]}),
            )
        assert (read.status_code, write.status_code) == (200, 200), (read.text, write.text)
        state = await _invariants(engine, body["id"])
        assert state["phase"] == "REST" and [log["value"] for log in state["logs"]] == [8]
        await engine.dispose()


@pytest.mark.parametrize("round_", range(ROUNDS))
async def test_pause_races_the_deadline(session, test_dsn, monkeypatch, clock, round_):
    """Пауза, поставленная до дедлайна, и чтение после дедлайна одновременно: либо пауза успела (фаза
    стоит), либо дедлайн записан первым (пауза — устаревший no-op). Обратного хода фазы нет."""
    user, body = await _prepared(session, 306130 + round_, clock, [REPS_2x8_R30])
    t0 = body["engine"]["state"]["started_at"]
    clock.ms = t0 + 6_000
    pause = _event("pause", {"phase_seq": 0}, at=t0 + 4_000)
    _gate(monkeypatch, LiveEngineService, "sync")
    with _per_request_sessions(test_dsn, user.telegram_id) as engine:
        async with _client() as c:
            read, write = await asyncio.gather(
                c.get(f"{LIVE}/active"), c.post(f"{LIVE}/{body['id']}/events", json={"events": [pause]}),
            )
        assert (read.status_code, write.status_code) == (200, 200), (read.text, write.text)
        state = await _invariants(engine, body["id"])
        assert (state["phase"], state["paused_at"]) in (("PREP", t0 + 4_000), ("WORK", None)), state
        await engine.dispose()


@pytest.mark.parametrize("round_", range(ROUNDS))
async def test_resume_vs_duplicate_resume(session, test_dsn, monkeypatch, clock, round_):
    user, body = await _prepared(session, 306140 + round_, clock, [REPS_2x8_R30])
    t0 = body["engine"]["state"]["started_at"]
    clock.ms = t0 + 2_000
    with _per_request_sessions(test_dsn, user.telegram_id) as engine:
        async with _client() as c:
            await c.post(f"{LIVE}/{body['id']}/events", json={"events": [_event("pause", {"phase_seq": 0})]})
        clock.ms = t0 + 100_000
        _gate(monkeypatch, LiveEngineService, "sync")
        async with _client() as c:
            a, b = await asyncio.gather(
                c.post(f"{LIVE}/{body['id']}/events", json={"events": [_event("resume", {"phase_seq": 0})]}),
                c.post(f"{LIVE}/{body['id']}/events", json={"events": [_event("resume", {"phase_seq": 0})]}),
            )
        assert (a.status_code, b.status_code) == (200, 200)
        assert sorted(r.json()["event_results"][0]["outcome"] for r in (a, b)) == ["applied", "noop"]
        state = await _invariants(engine, body["id"])
        assert state["phase_deadline_at"] == t0 + 103_000  # остаток 3 с — один раз
        await engine.dispose()


@pytest.mark.parametrize("round_", range(ROUNDS))
async def test_completion_vs_completion_credits_and_progresses_once(session, test_dsn, monkeypatch, clock, round_):
    """Курс STEP: два устройства одновременно завершают (finish_early и POST complete) — одно завершение,
    прогрессия применена ровно один раз, кредит занятия — один."""
    user = await _user(session, 306150 + round_)
    inclusion, _, plan_item_ids = await _setup_step_session(session, user)
    body = await _start(session, user, clock, plan_item_ids=[plan_item_ids["block_a"], plan_item_ids["block_b"]])
    await session.commit()
    t0 = body["engine"]["state"]["started_at"]
    clock.ms = t0 + 9_000
    with _per_request_sessions(test_dsn, user.telegram_id) as engine:
        async with _client() as c:
            await c.post(f"{LIVE}/{body['id']}/events", json={"events": [
                _event("submit_result", {"block_index": 0, "set_index": 0, "round_index": None, "value": 10}),
            ]})
        clock.ms = t0 + 20_000
        _gate(monkeypatch, LiveEngineService, "sync")
        async with _client() as c:
            a, b = await asyncio.gather(
                c.post(f"{LIVE}/{body['id']}/events", json={"events": [_event("finish_early")]}),
                c.post(f"{LIVE}/{body['id']}/complete", json={"abandoned": True, "effort": 3}),
            )
        assert (a.status_code, b.status_code) == (200, 200), (a.text, b.text)
        await _invariants(engine, body["id"])
        async with await _fresh(engine) as db:
            row = await db.get(TrainingSession, body["id"])
            assert row.status.value == "completed" and row.duration_source == "measured"
            assert row.plan_item_id is not None
            credited = await db.scalar(select(func.count()).select_from(TrainingSession).where(
                TrainingSession.plan_item_id == row.plan_item_id,
            ))
            assert credited == 1
            inc = await db.get(ProgramInclusion, inclusion["id"])
            assert (inc.progression_state_rev or 0) == 0  # досрочно — прогрессия пропущена, не дважды
        await engine.dispose()


@pytest.mark.parametrize("round_", range(ROUNDS))
async def test_completion_vs_correction(session, test_dsn, monkeypatch, clock, round_):
    """Последний подход (завершение) и правка предыдущего одновременно: нет дедлока, нет дубля, ревизия
    растёт только если правка пришла после завершения."""
    user, body = await _prepared(session, 306160 + round_, clock, [REPS_2x8_R30])
    t0 = body["engine"]["state"]["started_at"]
    clock.ms = t0 + 9_000
    with _per_request_sessions(test_dsn, user.telegram_id) as engine:
        async with _client() as c:
            await c.post(f"{LIVE}/{body['id']}/events", json={"events": [
                _event("submit_result", {"block_index": 0, "set_index": 0, "round_index": None, "value": 8}),
            ]})
            clock.ms = t0 + 45_000
            await c.get(f"{LIVE}/active")
        _gate(monkeypatch, LiveEngineService, "sync")
        async with _client() as c:
            a, b = await asyncio.gather(
                c.post(f"{LIVE}/{body['id']}/events", json={"events": [
                    _event("submit_result", {"block_index": 0, "set_index": 1, "round_index": None, "value": 7}),
                ]}),
                c.post(f"{LIVE}/{body['id']}/events", json={"events": [
                    _event("correct_previous", {"block_index": 0, "set_index": 0, "round_index": None, "value": 9}),
                ]}),
            )
        assert (a.status_code, b.status_code) == (200, 200), (a.text, b.text)
        state = await _invariants(engine, body["id"])
        assert state["status"] == "completed" and [log["value"] for log in state["logs"]] == [9, 7]
        async with await _fresh(engine) as db:
            row = await db.get(TrainingSession, body["id"])
            assert row.revision in (0, 1)
            values = sorted(str(v) for v in (await db.execute(
                select(SetLog.value).where(SetLog.session_id == body["id"]),
            )).scalars().all())
            assert values == ["7.00", "9.00"]
        await engine.dispose()


async def test_offline_rest_ends_before_reconnect_and_device_b_already_advanced(session, test_dsn, clock):
    """Офлайн-устройство A: подход, отдых истёк, следующий подход. Тем временем устройство B открыло сессию
    (проекция записала дедлайн). Очередь A досылается позже — результат тот же, без дублей."""
    user, body = await _prepared(session, 306170, clock, [REPS_2x8_R30, REPS_1x5])
    t0 = body["engine"]["state"]["started_at"]
    queue = [
        _event("submit_result", {"block_index": 0, "set_index": 0, "round_index": None, "value": 8}, at=t0 + 8_000),
        _event("submit_result", {"block_index": 0, "set_index": 1, "round_index": None, "value": 6}, at=t0 + 45_000),
    ]
    with _per_request_sessions(test_dsn, user.telegram_id) as engine:
        clock.ms = t0 + 5_500
        async with _client() as c:
            assert (await c.get(f"{LIVE}/active")).json()["session"]["engine"]["state"]["phase"] == "WORK"  # B
            clock.ms = t0 + 200_000
            synced = (await c.post(f"{LIVE}/{body['id']}/events", json={"events": queue})).json()  # A reconnect
        assert [r["outcome"] for r in synced["event_results"]] == ["applied", "applied"]
        state = await _invariants(engine, body["id"])
        assert [log["value"] for log in state["logs"]] == [8, 6]
        assert state["phase"] == "WORK" and state["cursor"]["block_index"] == 1  # блочный отдых истёк сам
        async with await _fresh(engine) as db:
            types = (await db.execute(
                select(SessionEvent.type, SessionEvent.server_at).where(SessionEvent.session_id == body["id"])
                .order_by(SessionEvent.seq),
            )).all()
            assert [t for t, _ in types] == [
                "start", "deadline", "submit_result", "deadline", "submit_result", "deadline", "deadline",
            ][: len(types)]
            assert types[1][1] == from_ms(t0 + 5_000)
        await engine.dispose()

