"""Ревью wave 13: двойной POST /sessions/live с одним client_session_id (офлайн-повтор старта /
двойной тап) — идемпотентность не должна заканчиваться 500 у проигравшего запроса."""

import asyncio
import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.db.models_program import TrainingSession
from app.services.live_session import LiveSessionService
from app.web.main import app
from tests.test_web.test_v2_live_session import _setup_step_session
from tests.test_web.test_v2_live_session_concurrency import _gate, _per_request_sessions


async def test_two_concurrent_starts_same_client_session_id_return_same_session(
    session, user: User, test_dsn, monkeypatch,
):
    _, _, plan_item_ids = await _setup_step_session(session, user)
    await session.commit()
    _gate(monkeypatch, LiveSessionService, "start_session")
    payload = {
        "client_session_id": str(uuid.uuid4()),
        "plan_item_ids": [plan_item_ids["block_a"], plan_item_ids["block_b"]],
    }
    with _per_request_sessions(test_dsn, user.telegram_id) as engine:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t") as c:
            first, second = await asyncio.gather(
                c.post("/api/v2/sessions/live", json=payload), c.post("/api/v2/sessions/live", json=payload),
            )
        assert (first.status_code, second.status_code) == (200, 200), (first.text, second.text)
        assert first.json()["id"] == second.json()["id"]
        async with async_sessionmaker(engine, class_=AsyncSession)() as fresh:
            count = await fresh.scalar(
                select(func.count()).select_from(TrainingSession).where(TrainingSession.user_id == user.id),
            )
        assert count == 1
        await engine.dispose()
