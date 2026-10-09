"""J11 (#307): один пользователь, параллельные запросы — ни второй сессии, ни второго кредита.

Как tests/test_web/test_v2_live_session_concurrency.py: каждый запрос — своя сессия/транзакция с
коммитом в конце (как app.web.db.get_session), вход в пишущий метод синхронизирован барьером, чтобы оба
запроса прошли чтение до того, как любой из них закоммитит."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models_program import TrainingSession
from app.services.live_session import LiveSessionService
from app.services.manual_session import ManualSessionService
from app.web.main import app
from tests.test_web._v2_client import v2_post
from tests.test_web.test_v2_live_session_concurrency import _gate, _per_request_sessions
from tests.test_web.test_v2_live_session_workout_start import _user
from tests.test_web.test_v2_training_session_v2 import REPS_2x8, _plan_item, _workout

ROUNDS = 3


async def _count(engine, model, *where) -> int:
    async with async_sessionmaker(engine, class_=AsyncSession)() as fresh:
        return await fresh.scalar(select(func.count()).select_from(model).where(*where))


@pytest.mark.parametrize("round_", range(ROUNDS))
async def test_parallel_manual_records_with_same_key_create_one_session(session, test_dsn, monkeypatch, round_):
    user = await _user(session, 307110 + round_)
    workout, [exercise] = await _workout(session, user, [REPS_2x8])
    await session.commit()
    exercise_id = exercise.id
    payload = {
        "source": "backdated", "performed_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        "workout_definition_id": workout.id, "client_session_id": str(uuid.uuid4()),
        "blocks": [{"exercise_id": exercise_id, "sets": [
            {"set_number": 1, "metric_type": "reps", "value": "8", "unit": "reps"},
        ]}],
    }
    _gate(monkeypatch, ManualSessionService, "record")

    with _per_request_sessions(test_dsn, user.telegram_id) as engine:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t") as c:
            first, second = await asyncio.gather(
                c.post("/api/v2/sessions", json=payload), c.post("/api/v2/sessions", json=payload),
            )
        assert (first.status_code, second.status_code) == (200, 200), (first.text, second.text)
        assert first.json()["id"] == second.json()["id"]
        assert await _count(engine, TrainingSession, TrainingSession.user_id == user.id) == 1
        await engine.dispose()


@pytest.mark.parametrize("round_", range(ROUNDS))
async def test_parallel_completions_of_planned_session_credit_once(session, test_dsn, monkeypatch, round_):
    user = await _user(session, 307120 + round_)
    workout, [exercise] = await _workout(session, user, [REPS_2x8])
    plan_item_id = await _plan_item(session, user, workout, exercise)
    started = await v2_post(session, user.telegram_id, "/api/v2/sessions/live", {
        "client_session_id": str(uuid.uuid4()), "plan_item_ids": [plan_item_id],
    })
    assert started.status_code == 200, started.text
    session_id = started.json()["id"]
    await session.commit()
    _gate(monkeypatch, LiveSessionService, "complete_session")
    path = f"/api/v2/sessions/live/{session_id}/complete"

    with _per_request_sessions(test_dsn, user.telegram_id) as engine:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t") as c:
            first, second = await asyncio.gather(
                c.post(path, json={"abandoned": False}), c.post(path, json={"abandoned": False}),
            )
        assert (first.status_code, second.status_code) == (200, 200), (first.text, second.text)
        assert sorted(r.json()["progression_skipped_reason"] for r in (first, second)) == [
            "already_completed", "no_program_inclusion",
        ]
        assert await _count(engine, TrainingSession, TrainingSession.user_id == user.id) == 1
        assert await _count(engine, TrainingSession, TrainingSession.plan_item_id == plan_item_id) == 1
        async with async_sessionmaker(engine, class_=AsyncSession)() as fresh:
            row = await fresh.get(TrainingSession, session_id)
            assert row.status.value == "completed" and row.ended_at is not None
            assert row.duration_source in ("measured", "unknown")
        await engine.dispose()
