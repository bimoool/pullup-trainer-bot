from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import SessionBlock, SessionStatus, SetLog, TrainingSession
from app.domain.multi_program import MetricType, SessionSource


@dataclass(frozen=True)
class SetLogInput:
    set_number: int
    metric_type: MetricType
    value: Decimal
    unit: str
    is_max_set: bool = False
    effort: Decimal | None = None
    note: str | None = None


@dataclass(frozen=True)
class SessionBlockInput:
    sets: list[SetLogInput]
    exercise_id: int | None = None
    complex_id: int | None = None


@dataclass(frozen=True)
class SessionSetLogDetail:
    set_number: int
    is_max_set: bool
    metric_type: MetricType
    value: Decimal
    unit: str
    effort: Decimal | None
    note: str | None


@dataclass(frozen=True)
class SessionBlockDetail:
    order_index: int
    exercise_id: int | None
    complex_id: int | None
    set_logs: list[SessionSetLogDetail] = field(default_factory=list)


@dataclass(frozen=True)
class SessionDetail:
    """Агрегат TrainingSession + SessionBlock + SetLog, собранный из трёх
    отдельных запросов (models_program.py волны 1 не заводит
    sqlalchemy.orm.relationship() между этими таблицами — только FK-колонки,
    см. докстринг модуля) — тот же принцип "репозиторий конвертирует ORM в
    датаклассы", что и WorkoutRecord/BlockLog у старой схемы, но здесь без
    домена: TrainingSession — не pull-up-специфичная сущность."""

    id: int
    source: SessionSource
    status: SessionStatus
    performed_at: datetime
    effort: Decimal | None
    comment: str | None
    blocks: list[SessionBlockDetail] = field(default_factory=list)


class TrainingSessionRepository:
    """Агрегат TrainingSession + SessionBlock + SetLog (issue #165, волна
    3). Пишет только факт — пересчёт прогрессии не входит в этот
    репозиторий, им занимается app.services.session_log.
    TrainingSessionLogService поверх ProgressionStrategy (волна 0), не
    дублирует расчёт здесь."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_session(
        self, *, user_id: int, source: SessionSource, performed_at: datetime,
        effort: Decimal | None, comment: str | None, blocks: list[SessionBlockInput],
    ) -> TrainingSession:
        training_session = TrainingSession(
            user_id=user_id, source=source, status=SessionStatus.COMPLETED,
            performed_at=performed_at, effort=effort, comment=comment,
        )
        self._session.add(training_session)
        await self._session.flush()

        for order_index, block in enumerate(blocks):
            session_block = SessionBlock(
                session_id=training_session.id, order_index=order_index,
                exercise_id=block.exercise_id, complex_id=block.complex_id,
            )
            self._session.add(session_block)
            await self._session.flush()
            for set_log in block.sets:
                self._session.add(
                    SetLog(
                        session_block_id=session_block.id, set_number=set_log.set_number,
                        is_max_set=set_log.is_max_set, metric_type=set_log.metric_type,
                        value=set_log.value, unit=set_log.unit, effort=set_log.effort, note=set_log.note,
                    ),
                )
        await self._session.flush()
        return training_session

    async def _load_details(self, sessions: list[TrainingSession]) -> list[SessionDetail]:
        if not sessions:
            return []
        session_ids = [s.id for s in sessions]
        blocks_result = await self._session.execute(
            select(SessionBlock).where(SessionBlock.session_id.in_(session_ids)).order_by(
                SessionBlock.session_id, SessionBlock.order_index,
            ),
        )
        blocks = list(blocks_result.scalars().all())

        block_ids = [b.id for b in blocks]
        set_logs_by_block: dict[int, list[SetLog]] = {block_id: [] for block_id in block_ids}
        if block_ids:
            logs_result = await self._session.execute(
                select(SetLog).where(SetLog.session_block_id.in_(block_ids)).order_by(
                    SetLog.session_block_id, SetLog.set_number,
                ),
            )
            for log in logs_result.scalars().all():
                set_logs_by_block[log.session_block_id].append(log)

        blocks_by_session: dict[int, list[SessionBlock]] = {session_id: [] for session_id in session_ids}
        for block in blocks:
            blocks_by_session[block.session_id].append(block)

        details = []
        for session_row in sessions:
            block_details = [
                SessionBlockDetail(
                    order_index=block.order_index, exercise_id=block.exercise_id, complex_id=block.complex_id,
                    set_logs=[
                        SessionSetLogDetail(
                            set_number=log.set_number, is_max_set=log.is_max_set, metric_type=log.metric_type,
                            value=log.value, unit=log.unit, effort=log.effort, note=log.note,
                        )
                        for log in set_logs_by_block[block.id]
                    ],
                )
                for block in blocks_by_session[session_row.id]
            ]
            details.append(
                SessionDetail(
                    id=session_row.id, source=session_row.source, status=session_row.status,
                    performed_at=session_row.performed_at, effort=session_row.effort,
                    comment=session_row.comment, blocks=block_details,
                ),
            )
        return details

    async def list_for_user(self, user_id: int, *, limit: int = 50, offset: int = 0) -> list[SessionDetail]:
        """offset/limit — срез уже загруженного списка (тот же приём, что
        GET /api/history, issue #50), не отдельный SQL LIMIT/OFFSET —
        типичный объём истории одного пользователя не требует БД-пагинации,
        см. CLAUDE.md."""
        result = await self._session.execute(
            select(TrainingSession).where(TrainingSession.user_id == user_id).order_by(
                TrainingSession.performed_at.desc(),
            ),
        )
        all_sessions = list(result.scalars().all())
        page = all_sessions[offset:offset + limit]
        return await self._load_details(page)

    async def get_for_user(self, session_id: int, user_id: int) -> SessionDetail | None:
        result = await self._session.execute(
            select(TrainingSession).where(TrainingSession.id == session_id, TrainingSession.user_id == user_id),
        )
        training_session = result.scalar_one_or_none()
        if training_session is None:
            return None
        details = await self._load_details([training_session])
        return details[0]
