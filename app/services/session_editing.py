"""Правка и клонирование завершённой сессии из Журнала v2 (#262, #307).

issue #307 (TRAINING_SESSION_V2 §4): что можно править и копировать, решает ОДИН чистый предикат
app.domain.training_session_v2.edit_verdict (ED1) — сервер сериализует его, у фронтенда эвристик нет.
Удаление по-прежнему решает более строгий предикат безопасного удаления (app.services.session_deletion,
PROJECT_SPEC §3) — правка и удаление больше не совпадают: например, запись «Тренировку из моих» системной
тренировки правится, но не удаляется. Подходы сессии, учтённой прогрессией курса, не правятся (их
значения питали прогрессию; заметки и усилие подхода — можно). Ни пересчёта прогрессии, ни каскада:
правка меняет только факт самой сессии; каждая правка — revision + 1 (ED2); снимок рецепта не
меняется никогда (ED3). Смена даты не меняет длительность (R4)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, tzinfo
from decimal import Decimal
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.training_sessions import TrainingSessionRepository
from app.domain.activity_types import ACTIVITY_TYPES, MAX_ACTIVITY_SECONDS, MIN_ACTIVITY_SECONDS
from app.domain.multi_program import SessionSource
from app.domain.training_session_v2 import EditField
from app.services.training_session_v2 import TrainingSessionV2Service

MAX_DISTANCE_METERS = 1_000_000  # «явно абсурдный ввод», не норма


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
        self._v2 = TrainingSessionV2Service(session)

    async def _locked(self, session_id: int, user_id: int):
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail is None:
            return None, None, EditOutcome(EditStatus.NOT_FOUND)
        await self._sessions.lock_session(session_id)
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail is None:  # конкурентное удаление — как "не найдена"
            return None, None, EditOutcome(EditStatus.NOT_FOUND)
        verdict = (await self._v2.verdicts([detail], user_id))[detail.id].edit
        return detail, verdict, None

    async def edit(
        self, session_id: int, user_id: int, tz: tzinfo, *, performed_on: date | None,
        effort: tuple[Decimal | None] | None, comment: tuple[str | None] | None, sets: list[SetEdit],
        now: datetime, duration_seconds: tuple[int | None] | None = None, activity_type: str | None = None,
        distance_meters: tuple[int | None] | None = None,
    ) -> EditOutcome:
        detail, verdict, failure = await self._locked(session_id, user_id)
        if failure is not None:
            return failure
        if not verdict.can_edit:
            return EditOutcome(EditStatus.DENIED, verdict.reason)

        requested: set[EditField] = set()
        if performed_on is not None:
            requested.add(EditField.DATE)
        if effort is not None:
            requested.add(EditField.EFFORT)
        if comment is not None:
            requested.add(EditField.COMMENT)
        if duration_seconds is not None:
            requested.add(EditField.DURATION)
        if activity_type is not None:
            requested.add(EditField.ACTIVITY_TYPE)
        if distance_meters is not None:
            requested.add(EditField.DISTANCE)

        blocks = {b.order_index: b for b in detail.blocks}
        seen: set[tuple[int, int]] = set()
        for edit in sets:
            block = blocks.get(edit.block_index)
            key = (edit.block_index, edit.set_number)
            log = next((log for log in block.set_logs if log.set_number == edit.set_number), None) if block else None
            if log is None or key in seen:
                return EditOutcome(EditStatus.INVALID, f"Подход {edit.set_number} блока {edit.block_index} не найден.")
            seen.add(key)
            requested.add(EditField.SET_ACTUALS if edit.value != log.value else EditField.SET_NOTES)

        denied = requested - verdict.fields
        if denied:
            return EditOutcome(EditStatus.DENIED, verdict.reason or "Это поле у этой тренировки не меняется.")

        if duration_seconds is not None and duration_seconds[0] is not None and not (
            MIN_ACTIVITY_SECONDS <= duration_seconds[0] <= MAX_ACTIVITY_SECONDS
        ):
            return EditOutcome(EditStatus.INVALID, "Длительность — от 1 минуты до 12 часов.")
        if activity_type is not None and activity_type not in ACTIVITY_TYPES:
            return EditOutcome(EditStatus.INVALID, "Неизвестный тип активности.")
        if distance_meters is not None and distance_meters[0] is not None and not (
            0 < distance_meters[0] <= MAX_DISTANCE_METERS
        ):
            return EditOutcome(EditStatus.INVALID, "Дистанция должна быть положительной.")

        performed_at = None
        if performed_on is not None:
            local_time = detail.performed_at.astimezone(tz).time()
            resolved = resolve_performed_at(performed_on, tz, time_of_day=local_time, now=now)
            if isinstance(resolved, str):
                return EditOutcome(EditStatus.INVALID, resolved)
            performed_at = resolved

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
            duration_seconds=duration_seconds, activity_type=activity_type, distance_meters=distance_meters,
        )
        return EditOutcome(EditStatus.OK, session_id=session_id)

    async def clone(
        self, session_id: int, user_id: int, tz: tzinfo, *, performed_on: date | None, now: datetime,
    ) -> EditOutcome:
        detail, verdict, failure = await self._locked(session_id, user_id)
        if failure is not None:
            return failure
        if not verdict.can_clone:
            return EditOutcome(EditStatus.DENIED, verdict.reason)
        today = now.astimezone(tz).date()
        day = performed_on or today
        time_of_day = now.astimezone(tz).time() if day == today else time(12, 0)
        resolved = resolve_performed_at(day, tz, time_of_day=time_of_day, now=now)
        if isinstance(resolved, str):
            return EditOutcome(EditStatus.INVALID, resolved)
        clone_id = await self._v2.clone(detail, user_id, performed_at=resolved, now=now)
        return EditOutcome(EditStatus.OK, session_id=clone_id)
