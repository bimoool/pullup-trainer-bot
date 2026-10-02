"""Правка и клонирование завершённой сессии из Журнала v2 (#262).

Работают ТОЛЬКО для сессий, прошедших тот же предикат безопасности, что и
удаление (app.services.session_deletion, PROJECT_SPEC §3): Builder-сессия,
независимая от защищённой прогрессии. Program-backed/STEP — отказ (409).
Ни пересчёта прогрессии, ни каскада: правка меняет только факт самой сессии."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, tzinfo
from decimal import Decimal
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.training_sessions import SessionDetail, TrainingSessionRepository
from app.domain.multi_program import SessionSource
from app.services.session_deletion import SessionDeletionService

REASON_ELECTIVE_NO_CLONE = "Факультатив нельзя повторить копией — запись вне плана записывается один раз."


class EditStatus(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    DENIED = "denied"
    INVALID = "invalid"


@dataclass(frozen=True)
class SetEdit:
    block_index: int
    set_number: int
    value: Decimal
    effort: Decimal | None
    note: str | None


@dataclass(frozen=True)
class EditOutcome:
    status: EditStatus
    detail: str | None = None  # причина отказа/ошибки валидации
    session_id: int | None = None


def resolve_performed_at(day: date, tz: tzinfo, *, time_of_day: time, now: datetime) -> datetime | str:
    """Локальный день пользователя + время суток -> UTC-момент; строка — ошибка.
    Будущее не допускается; сегодняшний день ограничивается "сейчас"."""
    if day > now.astimezone(tz).date():
        return "Дата не может быть в будущем."
    moment = datetime.combine(day, time_of_day, tzinfo=tz).astimezone(UTC)
    return min(moment, now)


class SessionEditingService:
    def __init__(self, session: AsyncSession) -> None:
        self._sessions = TrainingSessionRepository(session)
        self._deletion = SessionDeletionService(session)

    async def _locked_safe(self, session_id: int, user_id: int) -> tuple[SessionDetail | None, EditOutcome | None]:
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail is None:
            return None, EditOutcome(EditStatus.NOT_FOUND)
        await self._sessions.lock_session(session_id)
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail is None:  # конкурентное удаление — как "не найдена"
            return None, EditOutcome(EditStatus.NOT_FOUND)
        verdict = (await self._deletion.evaluate([detail], user_id))[detail.id]
        if not verdict.can_delete:
            return None, EditOutcome(EditStatus.DENIED, verdict.reason)
        return detail, None

    async def edit(
        self, session_id: int, user_id: int, tz: tzinfo, *, performed_on: date | None,
        effort: tuple[Decimal | None] | None, comment: tuple[str | None] | None, sets: list[SetEdit],
        now: datetime,
    ) -> EditOutcome:
        detail, failure = await self._locked_safe(session_id, user_id)
        if failure is not None:
            return failure

        performed_at = None
        if performed_on is not None:
            local_time = detail.performed_at.astimezone(tz).time()
            resolved = resolve_performed_at(performed_on, tz, time_of_day=local_time, now=now)
            if isinstance(resolved, str):
                return EditOutcome(EditStatus.INVALID, resolved)
            performed_at = resolved

        blocks = {b.order_index: b for b in detail.blocks}
        seen: set[tuple[int, int]] = set()
        for edit in sets:
            block = blocks.get(edit.block_index)
            key = (edit.block_index, edit.set_number)
            if block is None or all(log.set_number != edit.set_number for log in block.set_logs) or key in seen:
                return EditOutcome(EditStatus.INVALID, f"Подход {edit.set_number} блока {edit.block_index} не найден.")
            seen.add(key)

        for edit in sets:
            note = edit.note
            if detail.source == SessionSource.ELECTIVE:
                # SetLog.note факультатива — упакованный backfill-ом JSON (формат/снаряд/подходы),
                # а не пользовательская заметка: правка значения/усилия его не затирает (#279).
                note = next(
                    (log.note for log in blocks[edit.block_index].set_logs if log.set_number == edit.set_number), None,
                )
            await self._sessions.update_set_log(
                blocks[edit.block_index].id, edit.set_number, value=edit.value, effort=edit.effort, note=note,
            )
        await self._sessions.update_session_fields(
            session_id, performed_at=performed_at, effort=effort, comment=comment,
        )
        return EditOutcome(EditStatus.OK, session_id=session_id)

    async def clone(
        self, session_id: int, user_id: int, tz: tzinfo, *, performed_on: date | None, now: datetime,
    ) -> EditOutcome:
        detail, failure = await self._locked_safe(session_id, user_id)
        if failure is not None:
            return failure
        if detail.source == SessionSource.ELECTIVE:
            return EditOutcome(EditStatus.DENIED, REASON_ELECTIVE_NO_CLONE)
        today = now.astimezone(tz).date()
        day = performed_on or today
        time_of_day = now.astimezone(tz).time() if day == today else time(12, 0)
        resolved = resolve_performed_at(day, tz, time_of_day=time_of_day, now=now)
        if isinstance(resolved, str):
            return EditOutcome(EditStatus.INVALID, resolved)
        clone = await self._sessions.clone_session(detail.id, user_id=user_id, performed_at=resolved)
        return EditOutcome(EditStatus.OK, session_id=clone.id)
