"""Журнал событий Live Engine v2 (issue #306, LIVE_ENGINE_V2 §1) — только добавление.

Порядок блокировок: вызывающий УЖЕ держит строку сессии (TrainingSessionRepository.lock_session) —
seq назначается под ней, поэтому (session_id, seq) не гоняется."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import SessionEvent


class SessionEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_client_event_id(self, client_event_id: uuid.UUID) -> SessionEvent | None:
        result = await self._session.execute(
            select(SessionEvent).where(SessionEvent.client_event_id == client_event_id),
        )
        return result.scalar_one_or_none()

    async def list_for_session(self, session_id: int) -> list[SessionEvent]:
        result = await self._session.execute(
            select(SessionEvent).where(SessionEvent.session_id == session_id).order_by(SessionEvent.seq),
        )
        return list(result.scalars().all())

    async def next_seq(self, session_id: int) -> int:
        result = await self._session.execute(
            select(func.coalesce(func.max(SessionEvent.seq), -1)).where(SessionEvent.session_id == session_id),
        )
        return int(result.scalar_one()) + 1

    async def append(
        self, *, session_id: int, seq: int, type_: str, payload: dict, server_at: datetime, outcome: str,
        client_event_id: uuid.UUID | None = None, client_at: datetime | None = None,
    ) -> None:
        self._session.add(SessionEvent(
            session_id=session_id, seq=seq, client_event_id=client_event_id, type=type_, payload=payload,
            client_at=client_at, server_at=server_at, outcome=outcome,
        ))
        await self._session.flush()
