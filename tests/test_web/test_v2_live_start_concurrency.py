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


async def test_two_concurrent_starts_different_client_session_ids_one_wins_one_409(
    session, user: User, test_dsn, monkeypatch,
):
    """N1 (#293): два устройства (разные client_session_id) стартуют одновременно — advisory-лок
    на пользователя сериализует проверку «активной нет»: ровно одна STARTED-сессия, у второго 409."""
    _, _, plan_item_ids = await _setup_step_session(session, user)
    await session.commit()
    original = LiveSessionService.start_session
    barrier = asyncio.Barrier(2)
    calls = 0

    async def gated_once(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls <= 2:  # только два конкурентных старта ждут друг друга; повтор — без барьера
            await asyncio.wait_for(barrier.wait(), timeout=10)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(LiveSessionService, "start_session", gated_once)
    ids = [plan_item_ids["block_a"], plan_item_ids["block_b"]]
    first_id, second_id = str(uuid.uuid4()), str(uuid.uuid4())
    with _per_request_sessions(test_dsn, user.telegram_id) as engine:
        async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t") as c:
            first, second = await asyncio.gather(
                c.post("/api/v2/sessions/live", json={"client_session_id": first_id, "plan_item_ids": ids}),
                c.post("/api/v2/sessions/live", json={"client_session_id": second_id, "plan_item_ids": ids}),
            )
            codes = sorted((first.status_code, second.status_code))
            assert codes == [200, 409], (first.text, second.text)
            winner, winner_id = (first, first_id) if first.status_code == 200 else (second, second_id)
            # Повтор победителя с тем же client_session_id — та же сессия (идемпотентность не сломана).
            retry = await c.post(
                "/api/v2/sessions/live", json={"client_session_id": winner_id, "plan_item_ids": ids},
            )
            assert retry.status_code == 200 and retry.json()["id"] == winner.json()["id"]
        async with async_sessionmaker(engine, class_=AsyncSession)() as fresh:
            count = await fresh.scalar(
                select(func.count()).select_from(TrainingSession).where(TrainingSession.user_id == user.id),
            )
        assert count == 1
        await engine.dispose()
