"""Оркестрация Live Engine v2 (issue #306, docs/domain/LIVE_ENGINE_V2.md): сервер — единственный
источник переходов. Чистые переходы — app.domain.live_engine; здесь — время, журнал session_events,
запись подходов и завершение через канонический интерфейс #307 (LiveSessionService.complete_session).

Один путь записи на каждое событие (C4):
  lock строки сессии → (дубль client_event_id? → no-op) → client_at зажат в [last_at, now] →
  дедлайны до этого момента (события ``deadline`` с server_at = дедлайн) → само событие → в конце
  дедлайны до «сейчас» (ленивая проекция P3) → эффекты (SetLog, блоки, завершение/отмена) →
  состояние + зеркало колонок фазы v1.

Порядок блокировок тот же, что у sets:batch/complete: строка training_sessions FOR UPDATE; завершение
(#307) берёт ту же строку повторно внутри той же транзакции и затем инклюзию/план — цикла ожидания нет.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models_program import SessionPhase, SessionStatus, TrainingSession
from app.db.repositories.session_events import SessionEventRepository
from app.db.repositories.training_sessions import (
    EngineMirror,
    SessionDetail,
    TrainingSessionRepository,
)
from app.domain import live_engine as engine
from app.domain.multi_program import MetricType

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
OUTCOME_APPLIED = "applied"
OUTCOME_NOOP = "noop"
OUTCOME_DUPLICATE = "duplicate"

_PHASE_MIRROR = {
    engine.PREP: SessionPhase.GET_READY,
    engine.WORK: SessionPhase.GO,
    engine.RESULT: SessionPhase.GO,
    engine.REST: SessionPhase.REST,
    engine.COMPLETE: SessionPhase.DONE,
}
_SMALLINT_MAX = 32767


def _utcnow() -> datetime:
    """Серверное «сейчас» движка (подменяется в тестах детерминированными часами)."""
    return datetime.now(UTC)


def engine_now() -> datetime:
    """Те же часы, что у движка — для server_time ответа (C1: клиент считает server_offset от них)."""
    return _utcnow()


def to_ms(value: datetime) -> int:
    return (value - EPOCH) // timedelta(milliseconds=1)


def from_ms(value: int) -> datetime:
    return EPOCH + timedelta(milliseconds=value)


class EngineVersionMismatchError(Exception):
    """Эндпоинт движка v1 вызван для сессии v2 (или наоборот) — роут -> 409 engine_version_mismatch."""


class ClientEventConflictError(Exception):
    """client_event_id уже занят событием другой сессии — роут -> 422 (без раскрытия чужой сессии)."""


@dataclass(frozen=True)
class ClientEvent:
    client_event_id: uuid.UUID
    type: str
    payload: dict
    client_at: datetime | None


@dataclass(frozen=True)
class EventResult:
    client_event_id: uuid.UUID
    outcome: str  # applied | noop | duplicate


@dataclass(frozen=True)
class SyncResult:
    events: list[EventResult]
    completion: object | None  # CompleteResult, если сессия завершилась в этом запросе


def mirror(state: dict) -> EngineMirror:
    cursor = state["cursor"]
    return EngineMirror(
        phase_name=_PHASE_MIRROR[state["phase"]],
        phase_ends_at=from_ms(state["phase_deadline_at"]) if state["phase_deadline_at"] is not None else None,
        current_block_index=cursor["block_index"], current_set_number=cursor["set_index"] + 1,
        phase_index=min(state["phase_seq"], _SMALLINT_MAX),
    )


def _block_metric(plan: dict, block_index: int, set_index: int, is_extra: bool) -> tuple[MetricType, str]:
    block = plan["blocks"][block_index]
    if block["kind"] == engine.BLOCK_INTERVAL:
        return MetricType.REPS, "reps"
    sets = block["sets"]
    spec = sets[min(set_index, len(sets) - 1)] if not is_extra else sets[-1]
    if spec["kind"] in (engine.SET_TIME, engine.SET_MAX_TIME):
        return MetricType.TIME, "s"
    return MetricType.REPS, "reps"


def _decimal(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


class LiveEngineService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._sessions = TrainingSessionRepository(session)
        self._events = SessionEventRepository(session)

    # --- Старт ------------------------------------------------------------------------------

    async def initialize(self, session_id: int, user_id: int, *, plan: dict, at: datetime) -> None:
        """Событие start: состояние, первая запись журнала (seq 0) и эффекты старта (блок 0 начат)."""
        at_ms = to_ms(at)
        state, effects = engine.start(plan, at_ms)
        await self._events.append(
            session_id=session_id, seq=0, type_=engine.EV_START, payload={}, server_at=from_ms(at_ms),
            outcome=OUTCOME_APPLIED,
        )
        await self._sessions.save_engine(session_id, state=state, plan=plan, mirror=mirror(state))
        await self._apply_effects(session_id, user_id, plan, effects)

    # --- События и проекция -----------------------------------------------------------------

    async def sync(self, session_id: int, user_id: int, events: list[ClientEvent]) -> SyncResult | None:
        """None — сессии нет/чужая (404). Дубль client_event_id той же сессии — no-op (200)."""
        if await self._sessions.get_for_user(session_id, user_id) is None:
            return None
        await self._sessions.lock_session(session_id)
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail.engine_version != engine.ENGINE_VERSION or detail.engine_state is None:
            raise EngineVersionMismatchError()
        plan, state = detail.engine_plan, detail.engine_state
        now_ms = to_ms(_utcnow())
        seq = await self._events.next_seq(session_id)
        results: list[EventResult] = []
        effects: list[dict] = []
        for event in events:
            existing = await self._events.get_by_client_event_id(event.client_event_id)
            if existing is not None:
                if existing.session_id != session_id:
                    raise ClientEventConflictError()
                results.append(EventResult(event.client_event_id, OUTCOME_DUPLICATE))
                continue
            client_ms = to_ms(event.client_at) if event.client_at is not None else None
            at_ms = engine.clamp_client_at(client_ms, state["last_at"], now_ms)
            projected, deadline_events, step_effects = engine.project(plan, state, at_ms)
            seq = await self._append_deadlines(session_id, seq, deadline_events)
            after, event_effects = engine.advance(
                plan, projected, {"type": event.type, "payload": event.payload}, at_ms,
            )
            outcome = OUTCOME_APPLIED if after != projected else OUTCOME_NOOP
            await self._events.append(
                session_id=session_id, seq=seq, type_=event.type, payload=event.payload, server_at=from_ms(at_ms),
                outcome=outcome, client_event_id=event.client_event_id, client_at=event.client_at,
            )
            seq += 1
            state = after
            effects.extend(step_effects + event_effects)
            results.append(EventResult(event.client_event_id, outcome))
        state, deadline_events, step_effects = engine.project(plan, state, now_ms)
        await self._append_deadlines(session_id, seq, deadline_events)
        effects.extend(step_effects)
        await self._sessions.save_engine(session_id, state=state, mirror=mirror(state))
        completion = await self._apply_effects(session_id, user_id, plan, effects)
        return SyncResult(events=results, completion=completion)

    async def project_due(self, session_id: int, user_id: int) -> object | None:
        """Ленивая проекция на чтении (P3): истёкшие дедлайны записываются событиями ``deadline``
        (server_at = дедлайн). Ничего не истекло — без блокировки и записи. Возвращает CompleteResult,
        если проекция довела сессию до COMPLETE."""
        detail = await self._sessions.get_for_user(session_id, user_id)
        if detail is None or detail.engine_version != engine.ENGINE_VERSION or detail.engine_state is None:
            return None
        if not self._has_due_deadline(detail.engine_state, to_ms(_utcnow())):
            return None
        result = await self.sync(session_id, user_id, [])
        return result.completion if result is not None else None

    @staticmethod
    def _has_due_deadline(state: dict, now_ms: int) -> bool:
        deadline = state.get("phase_deadline_at")
        return (
            state.get("status") == engine.ACTIVE and state.get("paused_at") is None
            and deadline is not None and deadline <= now_ms
        )

    async def finish_from_complete(
        self, session_id: int, user_id: int, *, abandoned: bool,
    ) -> SyncResult | None:
        """HTTP ``POST …/complete`` для сессии v2 (интерфейс #307 сохраняется): активная сессия
        заканчивается серверным ``finish_early`` (тем же путём, что событие клиента); уже завершённая —
        ничего не меняет (оценку/заметку затем дописывает идемпотентный complete_session)."""
        del abandoned  # движок сам решает: недоделанные плановые подходы ⇒ abandoned (T4)
        return await self.sync(session_id, user_id, [ClientEvent(
            client_event_id=uuid.uuid4(), type=engine.EV_FINISH_EARLY, payload={}, client_at=None,
        )])

    async def rebuild_state(self, session_id: int) -> dict | None:
        """Свёртка журнала событий (контракт §1: должна совпасть с engine_state)."""
        training_session = await self._sessions.lock_session(session_id)
        if training_session is None or training_session.engine_plan is None:
            return None
        events = [
            {"type": row.type, "at": to_ms(row.server_at), "payload": row.payload}
            for row in await self._events.list_for_session(session_id)
        ]
        return engine.rebuild(training_session.engine_plan, events)

    async def _append_deadlines(self, session_id: int, seq: int, deadline_events: list[dict]) -> int:
        for event in deadline_events:
            await self._events.append(
                session_id=session_id, seq=seq, type_=engine.EV_DEADLINE, payload={},
                server_at=from_ms(event["at"]), outcome=OUTCOME_APPLIED,
            )
            seq += 1
        return seq

    # --- Эффекты -----------------------------------------------------------------------------

    async def _apply_effects(self, session_id: int, user_id: int, plan: dict, effects: list[dict]) -> object | None:
        completion = None
        for effect in effects:
            kind = effect["type"]
            if kind in (engine.FX_SET_LOGGED, engine.FX_SET_CORRECTED):
                await self._write_log(session_id, plan, effect["log"], corrected=kind == engine.FX_SET_CORRECTED)
            elif kind == engine.FX_BLOCK_STARTED:
                await self._sessions.start_engine_block(session_id, effect["block_index"], from_ms(effect["at"]))
            elif kind == engine.FX_BLOCK_FINISHED:
                await self._sessions.finish_block(
                    session_id, effect["block_index"], ended_at=from_ms(effect["at"]),
                    result=self._interval_result(plan, effect),
                )
            elif kind == engine.FX_COMPLETED:
                completion = await self._complete(session_id, user_id, effect)
            elif kind == engine.FX_CANCELLED:
                state = (await self._sessions.get_for_user(session_id, user_id)).engine_state
                await self._sessions.mark_engine_cancelled(session_id, ended_at=from_ms(state["ended_at"]))
        return completion

    async def _write_log(self, session_id: int, plan: dict, log: dict, *, corrected: bool) -> None:
        if log["value"] is None:
            return  # раунд интервала без введённых повторов: подход не выдумывается (нет «0 повт.»)
        metric, unit = _block_metric(plan, log["block_index"], log["set_index"], log["is_extra"])
        await self._sessions.upsert_engine_set_log(
            session_id, block_index=log["block_index"], set_number=log["set_index"] + 1,
            log_index=log["log_index"], value=_decimal(log["value"]), effort=_decimal(log["effort"]),
            note=log["note"], is_extra=log["is_extra"], round_index=log["round_index"], metric_type=metric, unit=unit,
        )
        row = await self._session.get(TrainingSession, session_id)
        if corrected and row.status == SessionStatus.COMPLETED:
            await self._sessions.bump_revision(session_id)  # ED2: правка завершённой — +1 ревизия

    @staticmethod
    def _interval_result(plan: dict, effect: dict) -> dict | None:
        block = plan["blocks"][effect["block_index"]]
        if block["kind"] != engine.BLOCK_INTERVAL:
            return None
        interval = block["interval"]
        started = effect.get("started_at")
        ended = effect["at"]
        return {
            "type": "interval",
            "started_at": from_ms(started).isoformat() if started is not None else None,
            "completed_at": from_ms(ended).isoformat(),
            "planned_duration_seconds": interval["rounds"] * (interval["work_seconds"] + interval["rest_seconds"]),
            "actual_duration_seconds": max(0, (ended - started) // 1000) if started is not None else 0,
            "completed_cycles": effect.get("completed_rounds", 0),
        }

    async def _complete(self, session_id: int, user_id: int, effect: dict) -> object | None:
        """Канонический интерфейс завершения #307 — единственный писатель завершения."""
        from app.services.live_session import (
            LiveSessionService,  # цикл импорта live_session ↔ live_engine
        )

        state = (await self._sessions.get_for_user(session_id, user_id)).engine_state
        result, _ = await LiveSessionService(self._session).complete_session(
            session_id=session_id, user_id=user_id, abandoned=effect["abandoned"],
            active_elapsed_ms=effect["active_elapsed_ms"], ended_at=from_ms(state["ended_at"]),
        )
        return result


def engine_view(detail: SessionDetail, now: datetime) -> dict | None:
    """Ответ клиенту: план, состояние, серверное время (C1: server_offset) и аудио-хуки (§6)."""
    if detail.engine_version != engine.ENGINE_VERSION or detail.engine_state is None:
        return None
    return {
        "plan": detail.engine_plan,
        "state": detail.engine_state,
        "server_time_ms": to_ms(now),
        "timeline": engine.timeline(detail.engine_plan, detail.engine_state),
    }
