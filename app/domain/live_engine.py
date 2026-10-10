"""Live Engine v2 — одна детерминированная машина состояний живой тренировки (issue #306,
docs/domain/LIVE_ENGINE_V2.md).

Контракт C3: переходы — одна чистая функция ``advance(state, event, at) -> (state', effects)``. Её
TypeScript-зеркало (``webapp-frontend/src/liveEngine.ts``) обязано вести себя байт-в-байт так же —
обе реализации прогоняются на ОДНИХ И ТЕХ ЖЕ JSON-векторах (``tests/fixtures/live_engine_vectors.json``,
pytest и vitest). Поэтому состояние, план и события — обычные JSON-словари (время — целые
миллисекунды UTC epoch), без dataclass-ов: одна форма данных на обеих сторонах.

Домен не знает времени выполнения: ``at`` всегда передаёт вызывающий (сервис — серверное «сейчас»,
зажатый ``client_at`` офлайн-события или дедлайн при проекции; клиент — ``Date.now() + server_offset``).

Фазы (§3): PREP → WORK → (RESULT) → REST → … → COMPLETE. Блоки подходов, STEP-блоки курса, обычные
подходы и интервалы идут через один и тот же движок (P5): раунд интервала — это WORK/REST того же
курсора (``round_index``). Пауза (P1) — состояние движка, а не клиента: ``phase_deadline_at = None``,
``paused_remaining_ms`` хранит остаток, ``resume`` выдаёт новый дедлайн.

Решения реализации (зафиксированы в LIVE_ENGINE_V2 §9):
- ``phase_seq`` растёт на каждой смене фазы (не на pause/resume и не на правках лога) — токен CAS
  для управляющих событий (skip_wait/pause/resume/stop). Событие результата адресуется курсором
  (block/set/round), а не номером фазы: подход, отправленный офлайн, не теряется из-за дрожания часов
  на границе дедлайна PREP.
- ``time``-подход: на дедлайне WORK результат = цель (T3, без ожидания); исправление —
  ``correct_previous``. ``max_time``: ``stop`` → RESULT с измеренным значением (ждёт пользователя).
- Интервал с ``record_reps_per_round``: на дедлайне WORK — RESULT с дедлайном отдыха раунда (часы не
  останавливаются, тренировка идёт сама); ввод повторов в RESULT → REST с тем же дедлайном.
- ``add_extra_set`` несёт значение и фазу не двигает (#264: «не двигает фазу»), то есть
  «WORK(extra) → RESULT → назад, где был» схлопнуто в одно событие.
"""

from __future__ import annotations

import copy
from typing import Any

ENGINE_VERSION = 2

# Фазы и статусы (имена — контракт §1/§3).
PREP = "PREP"
WORK = "WORK"
RESULT = "RESULT"
REST = "REST"
COMPLETE = "COMPLETE"

ACTIVE = "active"
COMPLETED = "completed"
CANCELLED = "cancelled"

# Вид отдыха: после подхода, после блока, после раунда интервала.
REST_SET = "set"
REST_BLOCK = "block"
REST_ROUND = "round"

# События (контракт §3; ``start`` — только первое событие сессии).
EV_START = "start"
EV_DEADLINE = "deadline"
EV_SKIP_WAIT = "skip_wait"
EV_SUBMIT_RESULT = "submit_result"
EV_STOP = "stop"
EV_PAUSE = "pause"
EV_RESUME = "resume"
EV_FINISH_EARLY = "finish_early"
EV_CANCEL = "cancel"
EV_ADD_EXTRA_SET = "add_extra_set"
EV_CORRECT_PREVIOUS = "correct_previous"

CLIENT_EVENT_TYPES = frozenset({
    EV_SKIP_WAIT, EV_SUBMIT_RESULT, EV_STOP, EV_PAUSE, EV_RESUME, EV_FINISH_EARLY, EV_CANCEL,
    EV_ADD_EXTRA_SET, EV_CORRECT_PREVIOUS,
})

# Виды подходов (WORKOUT_DOMAIN_V2 §3).
SET_REPS = "reps"
SET_MAX_REPS = "max_reps"
SET_TIME = "time"
SET_MAX_TIME = "max_time"

BLOCK_SETS = "sets"
BLOCK_INTERVAL = "interval"

# Аудио-хуки (§6).
WARN_10S_MIN_PHASE_MS = 15_000
MAX_RESULT_VALUE = 99_999

# Эффекты (второй элемент advance): что сервис должен записать.
FX_SET_LOGGED = "set_logged"
FX_SET_CORRECTED = "set_corrected"
FX_BLOCK_STARTED = "block_started"
FX_BLOCK_FINISHED = "block_finished"
FX_COMPLETED = "completed"
FX_CANCELLED = "cancelled"


class EngineError(ValueError):
    """Невалидный план (не событие: невалидное/устаревшее событие — no-op, §2 C4)."""


# ============================================================================
# План
# ============================================================================


def validate_plan(plan: dict[str, Any]) -> None:
    """План — неизменяемый вход движка, построенный при старте из PrescriptionSnapshot."""
    blocks = plan.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise EngineError("plan.blocks: нужен хотя бы один блок")
    for index, block in enumerate(blocks):
        kind = block.get("kind")
        if not isinstance(block.get("prep_seconds"), int) or block["prep_seconds"] < 0:
            raise EngineError(f"blocks[{index}].prep_seconds")
        rest_block = block.get("rest_after_block_seconds")
        if rest_block is not None and (not isinstance(rest_block, int) or rest_block < 0):
            raise EngineError(f"blocks[{index}].rest_after_block_seconds")
        if kind == BLOCK_SETS:
            sets = block.get("sets")
            if not isinstance(sets, list) or not sets:
                raise EngineError(f"blocks[{index}].sets: нужен хотя бы один подход")
            for set_index, set_ in enumerate(sets):
                if set_.get("kind") not in (SET_REPS, SET_MAX_REPS, SET_TIME, SET_MAX_TIME):
                    raise EngineError(f"blocks[{index}].sets[{set_index}].kind")
                if set_["kind"] == SET_TIME and (not isinstance(set_.get("target"), int) or set_["target"] < 1):
                    raise EngineError(f"blocks[{index}].sets[{set_index}].target")
                rest = set_.get("rest_after_seconds")
                if rest is not None and (not isinstance(rest, int) or rest < 0):
                    raise EngineError(f"blocks[{index}].sets[{set_index}].rest_after_seconds")
        elif kind == BLOCK_INTERVAL:
            interval = block.get("interval") or {}
            if not isinstance(interval.get("work_seconds"), int) or interval["work_seconds"] < 1:
                raise EngineError(f"blocks[{index}].interval.work_seconds")
            if not isinstance(interval.get("rest_seconds"), int) or interval["rest_seconds"] < 0:
                raise EngineError(f"blocks[{index}].interval.rest_seconds")
            if not isinstance(interval.get("rounds"), int) or interval["rounds"] < 1:
                raise EngineError(f"blocks[{index}].interval.rounds")
        else:
            raise EngineError(f"blocks[{index}].kind")


def _block(plan: dict[str, Any], block_index: int) -> dict[str, Any]:
    return plan["blocks"][block_index]


def _set_spec(plan: dict[str, Any], block_index: int, set_index: int) -> dict[str, Any]:
    return plan["blocks"][block_index]["sets"][set_index]


def _is_interval(plan: dict[str, Any], block_index: int) -> bool:
    return _block(plan, block_index)["kind"] == BLOCK_INTERVAL


def _prescribed_count(plan: dict[str, Any], block_index: int) -> int:
    block = _block(plan, block_index)
    return block["interval"]["rounds"] if block["kind"] == BLOCK_INTERVAL else len(block["sets"])


# ============================================================================
# Время и учёт активной длительности
# ============================================================================


def _ms_to_seconds(ms: int) -> int:
    """Округление половины вверх целочисленно — одинаково в Python и TS (round() в Python банковский)."""
    return (ms + 500) // 1000


def clamp_client_at(client_at: int | None, last_at: int, now: int) -> int:
    """C4: недоверенное client_at зажимается в [last_at, now]; без client_at — now."""
    if client_at is None:
        return max(last_at, now)
    return max(last_at, min(int(client_at), now)) if now >= last_at else last_at


def _accrue(state: dict[str, Any], at: int) -> None:
    """Активное время (паузы исключены) и активное время текущей фазы — до момента at."""
    since = state["active_since"]
    if since is not None and at > since:
        state["active_elapsed_ms"] += at - since
        state["phase_active_ms"] += at - since
    if since is not None:
        state["active_since"] = max(since, at)
    state["last_at"] = max(state["last_at"], at)


def _enter_phase(
    state: dict[str, Any], phase: str, at: int, *, duration_ms: int | None, block_index: int, set_index: int,
    round_index: int | None, rest_kind: str | None = None,
) -> None:
    state["phase"] = phase
    state["cursor"] = {"block_index": block_index, "set_index": set_index, "round_index": round_index}
    state["rest_kind"] = rest_kind
    state["phase_started_at"] = at
    state["phase_duration_ms"] = duration_ms
    state["phase_deadline_at"] = at + duration_ms if duration_ms is not None else None
    state["paused_at"] = None
    state["paused_remaining_ms"] = None
    state["phase_active_ms"] = 0
    state["pending_value"] = None
    state["phase_seq"] += 1


# ============================================================================
# Старт
# ============================================================================


def start(plan: dict[str, Any], at: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Событие ``start``: PREP первого блока, если ``prep_seconds > 0``, иначе его WORK (§3)."""
    validate_plan(plan)
    state: dict[str, Any] = {
        "engine_version": ENGINE_VERSION,
        "status": ACTIVE,
        "phase": PREP,
        "cursor": {"block_index": 0, "set_index": 0, "round_index": None},
        "rest_kind": None,
        "phase_started_at": at,
        "phase_duration_ms": None,
        "phase_deadline_at": None,
        "paused_at": None,
        "paused_remaining_ms": None,
        "phase_seq": -1,
        "active_elapsed_ms": 0,
        "active_since": at,
        "phase_active_ms": 0,
        "pending_value": None,
        "started_at": at,
        "ended_at": None,
        "last_at": at,
        "block_started_at": None,
        "logs": [],
    }
    effects: list[dict[str, Any]] = []
    _enter_block(plan, state, 0, at, effects)
    return state, effects


def _enter_block(
    plan: dict[str, Any], state: dict[str, Any], block_index: int, at: int, effects: list[dict[str, Any]],
) -> None:
    state["block_started_at"] = at
    effects.append({"type": FX_BLOCK_STARTED, "block_index": block_index, "at": at})
    prep = _block(plan, block_index)["prep_seconds"]
    round_index = 0 if _is_interval(plan, block_index) else None
    if prep > 0:
        _enter_phase(
            state, PREP, at, duration_ms=prep * 1000, block_index=block_index, set_index=0, round_index=round_index,
        )
    else:
        _enter_work(plan, state, block_index, 0, round_index, at)


def _enter_work(
    plan: dict[str, Any], state: dict[str, Any], block_index: int, set_index: int, round_index: int | None, at: int,
) -> None:
    block = _block(plan, block_index)
    if block["kind"] == BLOCK_INTERVAL:
        duration = block["interval"]["work_seconds"] * 1000
    else:
        spec = block["sets"][set_index]
        duration = spec["target"] * 1000 if spec["kind"] == SET_TIME else None
    _enter_phase(
        state, WORK, at, duration_ms=duration, block_index=block_index, set_index=set_index, round_index=round_index,
    )


# ============================================================================
# Журнал подходов (внутри состояния — rebuild из событий восстанавливает и его)
# ============================================================================


def _find_log(state: dict[str, Any], block_index: int, set_index: int, round_index: int | None) -> dict | None:
    for log in state["logs"]:
        if (
            log["block_index"] == block_index and log["set_index"] == set_index
            and log["round_index"] == round_index
        ):
            return log
    return None


def _append_log(
    state: dict[str, Any], effects: list[dict[str, Any]], *, block_index: int, set_index: int,
    round_index: int | None, value: float | None, is_extra: bool, at: int, effort: Any = None,
    note: Any = None,
) -> None:
    log = {
        "log_index": len(state["logs"]),
        "block_index": block_index,
        "set_index": set_index,
        "round_index": round_index,
        "value": value,
        "is_extra": is_extra,
        "effort": effort,
        "note": note,
        "logged_at": at,
    }
    state["logs"].append(log)
    effects.append({"type": FX_SET_LOGGED, "log": dict(log)})


def _valid_value(value: Any) -> bool:
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= MAX_RESULT_VALUE
    )


def _clean_effort(value: Any) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and 1 <= value <= 5:
        return value
    return None


def _clean_note(value: Any) -> Any:
    if isinstance(value, str) and value.strip():
        return value.strip()[:1000]
    return None


# ============================================================================
# Следующий шаг (§3 «Next-step rule»)
# ============================================================================


def _after_set(plan: dict[str, Any], state: dict[str, Any], at: int, effects: list[dict[str, Any]]) -> None:
    """Подход (block, set) закончен в момент at."""
    cursor = state["cursor"]
    block_index, set_index = cursor["block_index"], cursor["set_index"]
    sets = _block(plan, block_index)["sets"]
    if set_index < len(sets) - 1:
        rest = sets[set_index]["rest_after_seconds"] or 0
        if rest > 0:
            _enter_phase(
                state, REST, at, duration_ms=rest * 1000, block_index=block_index, set_index=set_index,
                round_index=None, rest_kind=REST_SET,
            )
        else:
            _enter_work(plan, state, block_index, set_index + 1, None, at)
        return
    _after_block(plan, state, at, effects)


def _after_round(plan: dict[str, Any], state: dict[str, Any], at: int, effects: list[dict[str, Any]]) -> None:
    """Отдых раунда интервала закончен (или его нет): следующий раунд либо конец блока."""
    cursor = state["cursor"]
    block_index, round_index = cursor["block_index"], cursor["round_index"]
    if round_index < _block(plan, block_index)["interval"]["rounds"] - 1:
        _enter_work(plan, state, block_index, round_index + 1, round_index + 1, at)
        return
    _after_block(plan, state, at, effects)


def _block_finished_effect(plan: dict[str, Any], state: dict[str, Any], block_index: int, at: int) -> dict:
    effect: dict[str, Any] = {
        "type": FX_BLOCK_FINISHED, "block_index": block_index, "started_at": state["block_started_at"], "at": at,
    }
    if _is_interval(plan, block_index):
        effect["completed_rounds"] = sum(
            1 for log in state["logs"] if log["block_index"] == block_index and not log["is_extra"]
        )
    return effect


def _after_block(plan: dict[str, Any], state: dict[str, Any], at: int, effects: list[dict[str, Any]]) -> None:
    block_index = state["cursor"]["block_index"]
    effects.append(_block_finished_effect(plan, state, block_index, at))
    if block_index < len(plan["blocks"]) - 1:
        rest = _block(plan, block_index)["rest_after_block_seconds"] or 0
        if rest > 0:
            cursor = state["cursor"]
            _enter_phase(
                state, REST, at, duration_ms=rest * 1000, block_index=block_index, set_index=cursor["set_index"],
                round_index=cursor["round_index"], rest_kind=REST_BLOCK,
            )
        else:
            _enter_block(plan, state, block_index + 1, at, effects)
        return
    _finish(plan, state, at, effects, abandoned=False)


def _finish(
    plan: dict[str, Any], state: dict[str, Any], at: int, effects: list[dict[str, Any]], *, abandoned: bool,
) -> None:
    _accrue(state, at)
    cursor = state["cursor"]
    state["phase"] = COMPLETE
    state["status"] = COMPLETED
    state["rest_kind"] = None
    state["phase_started_at"] = at
    state["phase_duration_ms"] = None
    state["phase_deadline_at"] = None
    state["paused_at"] = None
    state["paused_remaining_ms"] = None
    state["phase_active_ms"] = 0
    state["pending_value"] = None
    state["active_since"] = None
    state["ended_at"] = at
    state["phase_seq"] += 1
    state["cursor"] = dict(cursor)
    effects.append({"type": FX_COMPLETED, "abandoned": abandoned, "active_elapsed_ms": state["active_elapsed_ms"]})


def _all_prescribed_logged(plan: dict[str, Any], state: dict[str, Any]) -> bool:
    for block_index in range(len(plan["blocks"])):
        logged = {
            (log["set_index"], log["round_index"]) for log in state["logs"]
            if log["block_index"] == block_index and not log["is_extra"]
        }
        if len(logged) < _prescribed_count(plan, block_index):
            return False
    return True


# ============================================================================
# Дедлайн (авто-переходы T1–T3)
# ============================================================================


def _on_deadline(plan: dict[str, Any], state: dict[str, Any], at: int, effects: list[dict[str, Any]]) -> None:
    """Фаза с дедлайном закончилась в момент at (дедлайн или «Начать сейчас»)."""
    phase = state["phase"]
    cursor = state["cursor"]
    block_index = cursor["block_index"]
    if phase == PREP:
        _enter_work(plan, state, block_index, cursor["set_index"], cursor["round_index"], at)
        return
    if phase == WORK:
        if _is_interval(plan, block_index):
            interval = _block(plan, block_index)["interval"]
            round_index = cursor["round_index"]
            _append_log(
                state, effects, block_index=block_index, set_index=round_index, round_index=round_index,
                value=None, is_extra=False, at=at,
            )
            rest_ms = interval["rest_seconds"] * 1000
            if interval.get("record_reps_per_round"):
                _enter_phase(
                    state, RESULT, at, duration_ms=rest_ms, block_index=block_index, set_index=round_index,
                    round_index=round_index,
                )
                if rest_ms == 0:
                    _after_round(plan, state, at, effects)
            elif rest_ms > 0:
                _enter_phase(
                    state, REST, at, duration_ms=rest_ms, block_index=block_index, set_index=round_index,
                    round_index=round_index, rest_kind=REST_ROUND,
                )
            else:
                _after_round(plan, state, at, effects)
            return
        # time-подход: результат = цель (T3), без ожидания.
        spec = _set_spec(plan, block_index, cursor["set_index"])
        _append_log(
            state, effects, block_index=block_index, set_index=cursor["set_index"], round_index=None,
            value=spec["target"], is_extra=False, at=at,
        )
        _after_set(plan, state, at, effects)
        return
    if phase == RESULT:
        # Только RESULT раунда интервала имеет дедлайн (отдых раунда): ввод не обязателен.
        _after_round(plan, state, at, effects)
        return
    if phase == REST:
        rest_kind = state["rest_kind"]
        if rest_kind == REST_SET:
            _enter_work(plan, state, block_index, cursor["set_index"] + 1, None, at)
        elif rest_kind == REST_ROUND:
            _after_round(plan, state, at, effects)
        else:
            _enter_block(plan, state, block_index + 1, at, effects)


# ============================================================================
# advance — единственная функция переходов
# ============================================================================


def _noop(state: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return state, []


def _seq_matches(state: dict[str, Any], payload: dict[str, Any]) -> bool:
    return payload.get("phase_seq") == state["phase_seq"]


def _resume_at(state: dict[str, Any], at: int) -> None:
    remaining = state["paused_remaining_ms"]
    state["paused_at"] = None
    state["paused_remaining_ms"] = None
    state["active_since"] = at
    if remaining is not None:
        state["phase_deadline_at"] = at + remaining


def advance(
    plan: dict[str, Any], state: dict[str, Any], event: dict[str, Any], at: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(state', effects). Чистая: вход не мутируется. Невалидное, устаревшее или неприменимое
    событие — no-op (то же состояние, пустые эффекты), никогда не исключение (C4).

    ``at`` — момент события; вызывающий гарантирует ``at >= state.last_at`` (зажим client_at) и
    проецирует дедлайны до ``at`` ПЕРЕД событием (``project``). Здесь ``at`` ещё раз поднимается до
    ``last_at`` — время движка не идёт назад."""
    if state["status"] != ACTIVE and event.get("type") not in (EV_ADD_EXTRA_SET, EV_CORRECT_PREVIOUS):
        return _noop(state)
    at = max(int(at), state["last_at"])
    kind = event.get("type")
    payload = event.get("payload") or {}
    new = copy.deepcopy(state)
    effects: list[dict[str, Any]] = []

    if kind == EV_DEADLINE:
        deadline = new["phase_deadline_at"]
        if new["paused_at"] is not None or deadline is None or at < deadline:
            return _noop(state)
        _accrue(new, deadline)
        _on_deadline(plan, new, deadline, effects)
        return new, effects

    if kind == EV_SKIP_WAIT:
        # «Начать сейчас»: то же, что дедлайн сейчас — только для ожиданий (PREP, REST, RESULT раунда).
        if not _seq_matches(new, payload) or new["phase"] not in (PREP, REST, RESULT):
            return _noop(state)
        if new["phase"] == RESULT and new["phase_deadline_at"] is None and new["paused_remaining_ms"] is None:
            return _noop(state)  # RESULT max_time ждёт значения, «пропустить» нечего
        if new["paused_at"] is not None:
            _resume_at(new, at)
        _accrue(new, at)
        _on_deadline(plan, new, at, effects)
        return new, effects

    if kind == EV_PAUSE:
        if not _seq_matches(new, payload) or new["paused_at"] is not None or new["phase"] == COMPLETE:
            return _noop(state)
        _accrue(new, at)
        new["active_since"] = None
        new["paused_at"] = at
        if new["phase_deadline_at"] is not None:
            new["paused_remaining_ms"] = max(0, new["phase_deadline_at"] - at)
            new["phase_deadline_at"] = None
        return new, effects

    if kind == EV_RESUME:
        if not _seq_matches(new, payload) or new["paused_at"] is None:
            return _noop(state)
        _resume_at(new, at)
        new["last_at"] = max(new["last_at"], at)
        return new, effects

    if kind == EV_STOP:
        if not _seq_matches(new, payload) or new["phase"] != WORK:
            return _noop(state)
        cursor = new["cursor"]
        if _is_interval(plan, cursor["block_index"]):
            return _noop(state)
        spec = _set_spec(plan, cursor["block_index"], cursor["set_index"])
        if spec["kind"] not in (SET_TIME, SET_MAX_TIME):
            return _noop(state)
        if new["paused_at"] is not None:
            _resume_at(new, at)
        _accrue(new, at)
        measured = _ms_to_seconds(new["phase_active_ms"])
        if spec["kind"] == SET_TIME:
            _append_log(
                new, effects, block_index=cursor["block_index"], set_index=cursor["set_index"], round_index=None,
                value=measured, is_extra=False, at=at,
            )
            _after_set(plan, new, at, effects)
            return new, effects
        _enter_phase(
            new, RESULT, at, duration_ms=None, block_index=cursor["block_index"], set_index=cursor["set_index"],
            round_index=None,
        )
        new["pending_value"] = measured
        return new, effects

    if kind == EV_SUBMIT_RESULT:
        return _submit_result(plan, state, new, payload, at)

    if kind == EV_FINISH_EARLY:
        _accrue(new, at)
        cursor = new["cursor"]
        block_already_finished = new["phase"] == REST and new["rest_kind"] == REST_BLOCK
        block_began = new["phase"] != PREP or _block_has_logs(new, cursor["block_index"])
        if not block_already_finished and block_began:
            # Текущий блок прерван: его итог (для интервала — сделанные раунды) фиксируется.
            effects.append(_block_finished_effect(plan, new, cursor["block_index"], at))
        _finish(plan, new, at, effects, abandoned=not _all_prescribed_logged(plan, new))
        return new, effects

    if kind == EV_CANCEL:
        _accrue(new, at)
        new["phase"] = COMPLETE
        new["status"] = CANCELLED
        new["rest_kind"] = None
        new["phase_started_at"] = at
        new["phase_duration_ms"] = None
        new["phase_deadline_at"] = None
        new["paused_at"] = None
        new["paused_remaining_ms"] = None
        new["pending_value"] = None
        new["active_since"] = None
        new["ended_at"] = at
        new["phase_seq"] += 1
        effects.append({"type": FX_CANCELLED})
        return new, effects

    if kind == EV_ADD_EXTRA_SET:
        return _add_extra_set(plan, state, new, payload, at)

    if kind == EV_CORRECT_PREVIOUS:
        return _correct_previous(state, new, payload, at)

    return _noop(state)


def _block_has_logs(state: dict[str, Any], block_index: int) -> bool:
    return any(log["block_index"] == block_index for log in state["logs"])


def _submit_result(
    plan: dict[str, Any], state: dict[str, Any], new: dict[str, Any], payload: dict[str, Any], at: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Результат адресуется курсором: тот же подход/раунд, что сейчас исполняется. Подход уже
    записан (курсор ушёл дальше) — устаревший повтор, no-op."""
    cursor = new["cursor"]
    value = payload.get("value")
    if not _valid_value(value):
        return _noop(state)
    if payload.get("block_index") != cursor["block_index"] or payload.get("set_index") != cursor["set_index"]:
        return _noop(state)
    if payload.get("round_index") != cursor["round_index"]:
        return _noop(state)
    effort, note = _clean_effort(payload.get("effort")), _clean_note(payload.get("note"))
    block_index = cursor["block_index"]
    if _is_interval(plan, block_index):
        if new["phase"] != RESULT:
            return _noop(state)
        log = _find_log(new, block_index, cursor["set_index"], cursor["round_index"])
        if log is None:
            return _noop(state)
        log.update(value=value, effort=effort, note=note)
        effects = [{"type": FX_SET_CORRECTED, "log": dict(log)}]
        # Повторы раунда введены — оставшийся отдых раунда идёт как REST (тот же дедлайн).
        deadline, remaining = new["phase_deadline_at"], new["paused_remaining_ms"]
        new["phase"] = REST
        new["rest_kind"] = REST_ROUND
        new["phase_seq"] += 1
        new["phase_deadline_at"] = deadline
        new["paused_remaining_ms"] = remaining
        return new, effects
    if new["phase"] == PREP:
        # Дрожание часов на границе: сервер ещё в PREP этого же подхода — PREP заканчивается сейчас.
        if new["paused_at"] is not None:
            _resume_at(new, at)
        _accrue(new, at)
        _enter_work(plan, new, block_index, cursor["set_index"], None, at)
    if new["phase"] not in (WORK, RESULT):
        return _noop(state)
    if new["paused_at"] is not None:
        _resume_at(new, at)
    _accrue(new, at)
    effects: list[dict[str, Any]] = []
    _append_log(
        new, effects, block_index=block_index, set_index=cursor["set_index"], round_index=None, value=value,
        is_extra=False, at=at, effort=effort, note=note,
    )
    _after_set(plan, new, at, effects)
    return new, effects


def _add_extra_set(
    plan: dict[str, Any], state: dict[str, Any], new: dict[str, Any], payload: dict[str, Any], at: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """T6: подход сверх плана в блок, чьи плановые подходы уже сделаны; фаза не меняется."""
    if new["status"] == CANCELLED:
        return _noop(state)
    block_index = payload.get("block_index")
    value = payload.get("value")
    if not isinstance(block_index, int) or isinstance(block_index, bool) or not 0 <= block_index < len(plan["blocks"]):
        return _noop(state)
    block = _block(plan, block_index)
    if block["kind"] != BLOCK_SETS or not block.get("extra_sets_allowed", True) or not _valid_value(value):
        return _noop(state)
    logged = {log["set_index"] for log in new["logs"] if log["block_index"] == block_index and not log["is_extra"]}
    if len(logged) < len(block["sets"]):
        return _noop(state)
    extras = sum(1 for log in new["logs"] if log["block_index"] == block_index and log["is_extra"])
    new["last_at"] = max(new["last_at"], at)
    if new["active_since"] is not None:
        _accrue(new, at)
    effects: list[dict[str, Any]] = []
    _append_log(
        new, effects, block_index=block_index, set_index=len(block["sets"]) + extras, round_index=None,
        value=value, is_extra=True, at=at, effort=_clean_effort(payload.get("effort")),
        note=_clean_note(payload.get("note")),
    )
    return new, effects


def _correct_previous(
    state: dict[str, Any], new: dict[str, Any], payload: dict[str, Any], at: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Правит уже записанный подход/раунд (только лог, фаза не меняется)."""
    if new["status"] == CANCELLED:
        return _noop(state)
    value = payload.get("value")
    if not _valid_value(value):
        return _noop(state)
    log = _find_log(new, payload.get("block_index"), payload.get("set_index"), payload.get("round_index"))
    if log is None:
        return _noop(state)
    effort = _clean_effort(payload.get("effort")) if "effort" in payload else log["effort"]
    note = _clean_note(payload.get("note")) if "note" in payload else log["note"]
    if log["value"] == value and log["effort"] == effort and log["note"] == note:
        return _noop(state)
    log.update(value=value, effort=effort, note=note)
    new["last_at"] = max(new["last_at"], at)
    if new["active_since"] is not None:
        _accrue(new, at)
    return new, [{"type": FX_SET_CORRECTED, "log": dict(log)}]


# ============================================================================
# Проекция (P3) и перестроение из событий
# ============================================================================


def project(
    plan: dict[str, Any], state: dict[str, Any], now: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Все дедлайны, истёкшие к ``now``, — по порядку, каждый как событие ``deadline`` с ``at =
    дедлайн``. Останавливается на первой фазе, ждущей пользователя (без дедлайна), на паузе и на
    COMPLETE. Возвращает (state', deadline_events, effects); события сервер дописывает в
    session_events (server_at = дедлайн)."""
    events: list[dict[str, Any]] = []
    effects: list[dict[str, Any]] = []
    guard = 0
    while (
        state["status"] == ACTIVE and state["paused_at"] is None and state["phase_deadline_at"] is not None
        and state["phase_deadline_at"] <= now
    ):
        deadline = state["phase_deadline_at"]
        state, step_effects = advance(plan, state, {"type": EV_DEADLINE}, deadline)
        events.append({"type": EV_DEADLINE, "at": deadline})
        effects.extend(step_effects)
        guard += 1
        if guard > 10_000:  # защитный предел; план конечен, реально недостижимо
            raise EngineError("projection did not converge")
    return state, events, effects


def apply_event(
    plan: dict[str, Any], state: dict[str, Any], event: dict[str, Any], at: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Канонический шаг воспроизведения (сервер и клиент): сначала дедлайны до ``at`` (``project``),
    затем само событие. Возвращает (state', deadline_events, effects) — эффекты дедлайнов идут
    раньше эффектов события."""
    state, deadline_events, effects = project(plan, state, at)
    state, event_effects = advance(plan, state, event, at)
    return state, deadline_events, effects + event_effects


def rebuild(plan: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Свёртка журнала событий: ``[{type, at, payload}]``, первое — ``start``. Должна дать ровно
    сохранённое состояние (контракт §1)."""
    if not events or events[0].get("type") != EV_START:
        raise EngineError("first event must be start")
    state, _ = start(plan, events[0]["at"])
    for event in events[1:]:
        state, _ = advance(plan, state, event, event["at"])
    return state


# ============================================================================
# Аудио-хуки (§6)
# ============================================================================


def _phase_cues(plan: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    cues: list[dict[str, Any]] = []
    phase, deadline = state["phase"], state["phase_deadline_at"]
    if phase == WORK:
        cues.append({"type": "work_start", "at": state["phase_started_at"]})
    if phase == COMPLETE and state["status"] == COMPLETED:
        cues.append({"type": "workout_complete", "at": state["phase_started_at"]})
    if deadline is None:
        return cues
    duration = state["phase_duration_ms"] or 0
    if phase in (PREP, REST) and duration >= WARN_10S_MIN_PHASE_MS:
        cues.append({"type": "warn_10s", "at": deadline - 10_000})
    if phase in (PREP, REST, WORK):
        for n in (3, 2, 1):
            if duration >= n * 1000:
                cues.append({"type": f"count_{n}", "at": deadline - n * 1000})
    if phase == WORK:
        cues.append({"type": "work_end", "at": deadline})
    if phase == REST:
        cues.append({"type": "rest_end", "at": deadline})
    return cues


def timeline(plan: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    """Звуковые/вибро-события текущей и следующей фазы ``[{type, at}]`` по возрастанию ``at``.
    На паузе — пусто (дедлайна нет). UI сам отбрасывает прошедшие (P4: ничего ретроактивно)."""
    if state["status"] == CANCELLED or state["paused_at"] is not None:
        return []
    cues = _phase_cues(plan, state)
    if state["status"] == ACTIVE and state["phase_deadline_at"] is not None:
        nxt, _ = advance(plan, state, {"type": EV_DEADLINE}, state["phase_deadline_at"])
        if nxt["phase_seq"] != state["phase_seq"]:
            cues.extend(_phase_cues(plan, nxt))
    unique: dict[tuple[str, int], dict[str, Any]] = {}
    for cue in cues:
        unique[(cue["type"], cue["at"])] = cue
    order = {"rest_end": 0, "work_end": 0, "work_start": 1, "workout_complete": 2}
    return sorted(unique.values(), key=lambda cue: (cue["at"], order.get(cue["type"], 0), cue["type"]))
