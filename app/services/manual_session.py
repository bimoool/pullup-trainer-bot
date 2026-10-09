"""Ручная запись тренировки (POST /api/v2/sessions) — адаптер к каноническому слою TrainingSession v2
(issue #307, docs/domain/TRAINING_SESSION_V2.md §2, D9).

- ``workout_definition_id`` (manual_existing_workout, «Тренировку из моих»): рецепт разрешается ТЕМ ЖЕ
  путём, что у живого старта (LiveSessionService.resolve_workout): блоки, SetTarget, v1-снимок;
  факт — из введённых значений. Клиент шлёт блоки тренировки по порядку (пустой блок = упражнение не
  выполнялось); состав, не совпадающий с тренировкой, — 422, а не тихая перестановка.
- без определения — manual_custom (снимок синтезируется из введённого, unprescribed); активность —
  external_activity; source=plan с инклюзией — прежняя запись программы (прогрессия как раньше,
  source_v2 = planned_live).
- ``client_session_id`` — ключ идемпотентности: повтор с тем же ключом возвращает ту же сессию (не
  вторую); тот же глобально уникальный столбец и та же схема (advisory-лок пользователя + SAVEPOINT +
  уникальный индекс), что у живого старта. Ключ чужого пользователя — 422 без раскрытия.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.training_sessions import SessionBlockInput, TrainingSessionRepository
from app.domain.multi_program import SessionSource
from app.domain.training_session_v2 import (
    UNKNOWN_DURATION,
    SessionSourceV2,
    entered_duration,
    legacy_source_v2,
    measured_duration,
)
from app.services.live_session import LiveSessionService, lock_user_starts
from app.services.session_log import RecordSessionResult, TrainingSessionLogService
from app.services.training_session_v2 import TrainingSessionV2Service

WORKOUT_MISMATCH_MESSAGE = "Состав записи не совпадает с тренировкой — обнови экран и попробуй снова."
FOREIGN_KEY_MESSAGE = "client_session_id уже использован"


class ManualSessionError(ValueError):
    """Невалидная ручная запись (роут → 422)."""


@dataclass(frozen=True)
class ManualSessionRequest:
    source: SessionSource
    performed_at: datetime
    blocks: list[SessionBlockInput]
    effort: Decimal | None = None
    comment: str | None = None
    program_inclusion_id: int | None = None
    activity_type: str | None = None
    duration_seconds: int | None = None
    distance_meters: int | None = None
    workout_definition_id: int | None = None
    client_session_id: uuid.UUID | None = None
    timezone: str | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True)
class ManualSessionOutcome:
    result: RecordSessionResult | None
    inclusion_not_found: bool = False
    replayed: bool = False


class ManualSessionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._sessions = TrainingSessionRepository(session)

    async def record(self, user_id: int, request: ManualSessionRequest, *, now: datetime) -> ManualSessionOutcome:
        if request.client_session_id is not None:
            await lock_user_starts(self._session, user_id)
            existing = await self._sessions.get_by_client_session_id(user_id, request.client_session_id)
            if existing is not None:
                return await self._replay(existing.id, user_id)
            try:
                async with self._session.begin_nested():
                    return await self._record(user_id, request, now=now)
            except IntegrityError:
                existing = await self._sessions.get_by_client_session_id(user_id, request.client_session_id)
                if existing is None:
                    raise ManualSessionError(FOREIGN_KEY_MESSAGE) from None
                return await self._replay(existing.id, user_id)
        return await self._record(user_id, request, now=now)

    async def _replay(self, session_id: int, user_id: int) -> ManualSessionOutcome:
        detail = await self._sessions.get_for_user(session_id, user_id)
        return ManualSessionOutcome(
            RecordSessionResult(session=detail, progression_result=None, progression_skipped_reason="already_recorded"),
            replayed=True,
        )

    async def _record(self, user_id: int, request: ManualSessionRequest, *, now: datetime) -> ManualSessionOutcome:
        blocks = request.blocks
        targets = None
        workout_snapshot = None
        if request.workout_definition_id is not None:
            blocks, targets, workout_snapshot = await self._existing_workout_blocks(request)

        if request.source == SessionSource.BACKDATED and not any(block.sets for block in blocks):
            raise ManualSessionError("Введи хотя бы один подход")

        result, inclusion_not_found = await TrainingSessionLogService(self._session).record_session(
            user_id=user_id, source=request.source, performed_at=request.performed_at, effort=request.effort,
            comment=request.comment, blocks=blocks, program_inclusion_id=request.program_inclusion_id,
            completed_at=request.completed_at, activity_type=request.activity_type,
            duration_seconds=request.duration_seconds if request.activity_type is not None else None,
            targets_by_block=targets, workout_snapshot=workout_snapshot, client_session_id=request.client_session_id,
        )
        if inclusion_not_found:
            return ManualSessionOutcome(None, inclusion_not_found=True)

        source_v2 = self._source_v2(request)
        if source_v2 is SessionSourceV2.EXTERNAL_ACTIVITY:
            duration = entered_duration(request.duration_seconds)
        elif source_v2 is SessionSourceV2.PLANNED_LIVE:
            # Запись программы одним запросом (QA-путь, не Журнал): длительность — как аналитика и раньше
            # считала её (completed_at − performed_at в окне [1 мин, 6 ч]), иначе unknown.
            duration = measured_duration(result.session.performed_at, result.session.completed_at)
        else:
            duration = entered_duration(request.duration_seconds) if request.duration_seconds else UNKNOWN_DURATION
        detail = await TrainingSessionV2Service(self._session).stamp_new(
            result.session.id, user_id, source=source_v2, resolved_at=now,
            workout_definition_id=request.workout_definition_id,
            program_inclusion_id=request.program_inclusion_id if source_v2 is SessionSourceV2.PLANNED_LIVE else None,
            timezone=request.timezone, duration=duration, distance_meters=request.distance_meters,
        )
        return ManualSessionOutcome(
            RecordSessionResult(
                session=detail, progression_result=result.progression_result,
                progression_skipped_reason=result.progression_skipped_reason,
            ),
        )

    @staticmethod
    def _source_v2(request: ManualSessionRequest) -> SessionSourceV2:
        if request.workout_definition_id is not None:
            return SessionSourceV2.MANUAL_EXISTING_WORKOUT
        return legacy_source_v2(
            legacy_source=request.source.value, has_activity=request.activity_type is not None,
            has_workout_snapshot=False, is_live=False,
        )

    async def _existing_workout_blocks(self, request: ManualSessionRequest):
        """Рецепт известной тренировки — тем же резолвом, что у живого старта; введённые подходы
        ложатся на блоки тренировки по позиции."""
        resolved_blocks, targets, snapshot = await LiveSessionService(self._session).resolve_workout(
            request.workout_definition_id,
        )
        if len(resolved_blocks) != len(request.blocks) or any(
            resolved.exercise_id != sent.exercise_id or sent.complex_id is not None
            for resolved, sent in zip(resolved_blocks, request.blocks, strict=True)
        ):
            raise ManualSessionError(WORKOUT_MISMATCH_MESSAGE)
        blocks = [
            SessionBlockInput(exercise_id=resolved.exercise_id, sets=sent.sets)
            for resolved, sent in zip(resolved_blocks, request.blocks, strict=True)
        ]
        return blocks, targets, snapshot.model_dump(mode="json") if snapshot is not None else None
