"""Гонка "реконнект + Завершить" (fix/concurrent-set-batch, найдено при
PRE-G3 стабилизации): событие "online" и тап "Завершить" одновременно
досылают ОДИН И ТОТ ЖЕ накопленный офлайн-батч двумя параллельными
POST /sets:batch. Раньше репозиторий делал SELECT -> "нет строки" -> INSERT,
и второй запрос падал на uq_set_logs_session_set_index (HTTP 500) — а если
это был запрос, за которым шёл complete, тренировка не завершалась.

В отличие от остальных test_web-тестов (одна общая AsyncSession на все
HTTP-вызовы — конкуренции там нет по построению), здесь КАЖДЫЙ запрос
получает свою сессию/соединение и свою транзакцию с коммитом в конце — ровно
как app.web.db.get_session в проде. Детерминизм: asyncio.Barrier ставится
на вход в изменяющий метод сервиса, так что оба запроса гарантированно уже
прошли авторизацию/чтение сессии и входят в запись одновременно, до того как
любой из них закоммитил."""

import asyncio
import uuid
from contextlib import contextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import User
from app.db.models_program import ProgramInclusion, SetLog, TrainingSession
from app.services.live_session import LiveSessionService
from app.web.auth import get_validated_init_data
from app.web.db import get_session
from app.web.main import app
from tests.test_web._v2_client import _FakeInitData, _FakeWebAppUser, v2_post
from tests.test_web.test_v2_live_session import _setup_step_session

ROUNDS = 5


@contextmanager
def _per_request_sessions(test_dsn: str, telegram_id: int):
    """Та же семантика, что app.web.db.get_session: своя сессия на запрос,
    коммит только при успешном хендлере."""
    engine = create_async_engine(test_dsn)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _session_per_request():
        async with factory() as db_session:
            yield db_session
            await db_session.commit()

    app.dependency_overrides[get_validated_init_data] = (
        lambda: _FakeInitData(user=_FakeWebAppUser(id=telegram_id, first_name="Тест"))
    )
    app.dependency_overrides[get_session] = _session_per_request
    try:
        yield engine
    finally:
        app.dependency_overrides.clear()


def _gate(monkeypatch, cls, name: str, parties: int = 2):
    """Все `parties` вызовов cls.name ждут друг друга на входе — оба
    конкурентных запроса стартуют запись одновременно, не последовательно."""
    original = getattr(cls, name)
    barrier = asyncio.Barrier(parties)

    async def gated(self, *args, **kwargs):
        await asyncio.wait_for(barrier.wait(), timeout=10)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(cls, name, gated)


async def _start_session(session, user: User) -> tuple[int, dict[str, int], int]:
    inclusion, roles, plan_item_ids = await _setup_step_session(session, user)
    start = await v2_post(
        session, telegram_id=user.telegram_id, path="/api/v2/sessions/live",
        payload={
            "client_session_id": str(uuid.uuid4()),
            "plan_item_ids": [plan_item_ids["block_a"], plan_item_ids["block_b"]],
        },
    )
    assert start.status_code == 200
    await session.commit()
    return start.json()["id"], roles, inclusion["id"]


def _offline_batch(roles: dict[str, int]) -> dict:
    """Тот же батч, что копит e2e session-offline: 3 подхода A + 1 подход Б."""
    return {"sets": [
        {"set_index": 0, "block_index": 0, "exercise_id": roles["block_a"], "value": "10"},
        {"set_index": 1, "block_index": 0, "exercise_id": roles["block_a"], "value": "10"},
        {"set_index": 2, "block_index": 0, "exercise_id": roles["block_a"], "value": "10"},
        {"set_index": 3, "block_index": 1, "exercise_id": roles["block_b"], "value": "3"},
    ]}


async def _stored_logs(engine, session_id: int) -> list[tuple[int, int, int, str]]:
    async with async_sessionmaker(engine, class_=AsyncSession)() as fresh:
        rows = await fresh.execute(
            select(SetLog.set_index, SetLog.session_block_id, SetLog.set_number, SetLog.value)
            .where(SetLog.session_id == session_id).order_by(SetLog.set_index),
        )
        return [(r[0], r[1], r[2], str(r[3])) for r in rows.all()]


async def _session_state(engine, session_id: int, inclusion_id: int) -> tuple[str, dict, int]:
    async with async_sessionmaker(engine, class_=AsyncSession)() as fresh:
        training_session = await fresh.get(TrainingSession, session_id)
        inclusion = await fresh.get(ProgramInclusion, inclusion_id)
        sessions_count = await fresh.scalar(
            select(func.count()).select_from(TrainingSession).where(
                TrainingSession.user_id == training_session.user_id,
            ),
        )
        return training_session.status.value, inclusion.progression_state, sessions_count


def _assert_logs_once(logs: list[tuple[int, int, int, str]]) -> None:
    assert [log[0] for log in logs] == [0, 1, 2, 3]  # каждый set_index ровно один раз
    block_a_id = logs[0][1]
    block_b_id = logs[3][1]
    assert block_a_id != block_b_id
    # set_number не задублировался и не "уехал" (1,2,3 в блоке A, 1 в блоке Б).
    assert [(log[1], log[2]) for log in logs] == [
        (block_a_id, 1), (block_a_id, 2), (block_a_id, 3), (block_b_id, 1),
    ]
    assert [log[3] for log in logs] == ["10.00", "10.00", "10.00", "3.00"]


# A + C + E: два одинаковых батча одновременно -> оба 200, строки ровно по разу.
@pytest.mark.parametrize("round_", range(ROUNDS))
async def test_two_concurrent_identical_batches_converge_without_500(
    session, user: User, test_dsn, monkeypatch, round_,
):
    session_id, roles, _ = await _start_session(session, user)
    _gate(monkeypatch, LiveSessionService, "batch_sets")
    path = f"/api/v2/sessions/live/{session_id}/sets:batch"
    payload = _offline_batch(roles)

    with _per_request_sessions(test_dsn, user.telegram_id) as engine:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t") as c:
            first, second = await asyncio.gather(c.post(path, json=payload), c.post(path, json=payload))

        assert (first.status_code, second.status_code) == (200, 200), (first.text, second.text)
        for response in (first, second):
            body = response.json()
            assert [len(b["set_logs"]) for b in body["blocks"]] == [3, 1]
        _assert_logs_once(await _stored_logs(engine, session_id))
        await engine.dispose()


# B + D + F: реконнект-флаш (батч) параллельно с "Завершить" (тот же батч,
# затем complete) — эквивалент того, что делает фронтенд в окне реконнекта.
async def test_reconnect_flush_racing_complete_flush_completes_once(session, user: User, test_dsn, monkeypatch):
    session_id, roles, inclusion_id = await _start_session(session, user)
    _gate(monkeypatch, LiveSessionService, "batch_sets")
    base = f"/api/v2/sessions/live/{session_id}"
    payload = _offline_batch(roles)

    with _per_request_sessions(test_dsn, user.telegram_id) as engine:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t") as c:
            async def reconnect_flush():
                return await c.post(f"{base}/sets:batch", json=payload)

            async def complete_flush():
                batch = await c.post(f"{base}/sets:batch", json=payload)
                assert batch.status_code == 200, batch.text  # без этого фронт не дошёл бы до complete
                return await c.post(f"{base}/complete", json={"abandoned": False})

            reconnect, complete = await asyncio.gather(reconnect_flush(), complete_flush())

        assert reconnect.status_code == 200, reconnect.text
        assert complete.status_code == 200, complete.text
        body = complete.json()
        assert body["status"] == "completed"
        assert body["progression_skipped_reason"] is None
        progression = body["progression_result"]
        assert progression is not None

        _assert_logs_once(await _stored_logs(engine, session_id))
        status, state, sessions_count = await _session_state(engine, session_id, inclusion_id)
        assert status == "completed"
        assert sessions_count == 1  # одна строка Журнала
        assert state["block_a"]["target"] == progression["block_a"]["target_after"]
        assert state["block_b"]["target"] == progression["block_b"]["target_after"]
        await engine.dispose()


# D + E + F: два complete одновременно (двойной флаш с completeRequested) —
# завершение и прогрессия ровно один раз, второй ответ — идемпотентный 200.
@pytest.mark.parametrize("round_", range(ROUNDS))
async def test_two_concurrent_completes_apply_progression_once(session, user: User, test_dsn, monkeypatch, round_):
    session_id, roles, inclusion_id = await _start_session(session, user)
    base = f"/api/v2/sessions/live/{session_id}"

    with _per_request_sessions(test_dsn, user.telegram_id) as engine:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t") as c:
            batch = await c.post(f"{base}/sets:batch", json=_offline_batch(roles))
            assert batch.status_code == 200, batch.text
            _gate(monkeypatch, LiveSessionService, "complete_session")
            first, second = await asyncio.gather(
                c.post(f"{base}/complete", json={"abandoned": False}),
                c.post(f"{base}/complete", json={"abandoned": False}),
            )

        assert (first.status_code, second.status_code) == (200, 200), (first.text, second.text)
        bodies = [first.json(), second.json()]
        assert all(b["status"] == "completed" for b in bodies)
        applied = [b for b in bodies if b["progression_result"] is not None]
        assert len(applied) == 1  # прогрессия применена ровно одним из запросов
        duplicate = next(b for b in bodies if b["progression_result"] is None)
        assert duplicate["progression_skipped_reason"] == "already_completed"

        _assert_logs_once(await _stored_logs(engine, session_id))
        status, state, sessions_count = await _session_state(engine, session_id, inclusion_id)
        assert status == "completed"
        assert sessions_count == 1
        assert state["block_a"]["target"] == applied[0]["progression_result"]["block_a"]["target_after"]
        assert state["block_b"]["target"] == applied[0]["progression_result"]["block_b"]["target_after"]
        await engine.dispose()


# E + F: последовательный повтор (ответ на первый complete потерян, клиент
# повторяет флаш целиком: батч + complete) — 200, без повторной прогрессии.
async def test_retried_flush_after_completion_is_idempotent(session, user: User, test_dsn):
    session_id, roles, inclusion_id = await _start_session(session, user)
    base = f"/api/v2/sessions/live/{session_id}"
    payload = _offline_batch(roles)

    with _per_request_sessions(test_dsn, user.telegram_id) as engine:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t") as c:
            assert (await c.post(f"{base}/sets:batch", json=payload)).status_code == 200
            first = await c.post(f"{base}/complete", json={"abandoned": False})
            assert first.status_code == 200
            _, state_after_first, _ = await _session_state(engine, session_id, inclusion_id)

            retry_batch = await c.post(f"{base}/sets:batch", json=payload)
            retry = await c.post(f"{base}/complete", json={"abandoned": False})

        assert retry_batch.status_code == 200, retry_batch.text
        assert retry.status_code == 200, retry.text
        assert first.json()["progression_result"] is not None
        assert retry.json()["status"] == "completed"
        assert retry.json()["progression_result"] is None
        assert retry.json()["progression_skipped_reason"] == "already_completed"

        _assert_logs_once(await _stored_logs(engine, session_id))
        status, state, sessions_count = await _session_state(engine, session_id, inclusion_id)
        assert status == "completed"
        assert state == state_after_first  # вторая прогрессия не применилась
        assert sessions_count == 1
        await engine.dispose()
