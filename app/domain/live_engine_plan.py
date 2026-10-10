"""План Live Engine v2 (issue #306) — неизменяемый вход ``app.domain.live_engine``, строится один раз
при старте сессии.

Источник — PrescriptionSnapshot (WORKOUT_DOMAIN_V2 §5): у тренировки с версией определения v2 план
повторяет снимок 1:1 (подходы, отдых после подхода, отдых после блока, подготовка, интервал). Снимок,
синтезированный из целей сессии (STEP-блоки курса, legacy без версии, S4), отдыха/подготовки не несёт
(«не выдумываются» для истории) — для ИСПОЛНЕНИЯ движку они нужны, поэтому такие блоки получают
умолчания контракта (``fallback_block``): отдых между подходами — из v1-протокола блока, иначе
SYSTEM_DEFAULT_REST (90 с, §3.2 п.2); отдых после блока — 90 с (§9.1); подготовка — §3.6 (5 с у первого
блока и у блока, чей первый подход на время или интервал, иначе 0)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.domain.live_engine import (
    BLOCK_INTERVAL,
    BLOCK_SETS,
    SET_MAX_REPS,
    SET_MAX_TIME,
    SET_REPS,
    SET_TIME,
    validate_plan,
)

SYSTEM_DEFAULT_REST_SECONDS = 90
DEFAULT_BLOCK_REST_SECONDS = 90
DEFAULT_PREP_SECONDS = 5


def _set_from_snapshot(raw: Mapping[str, Any]) -> dict[str, Any]:
    kind = raw["kind"]
    target = raw.get("target_reps") if kind == SET_REPS else raw.get("target_seconds") if kind == SET_TIME else None
    return {"kind": kind, "target": target, "rest_after_seconds": raw.get("rest_after_seconds")}


def plan_block_from_snapshot(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Блок снимка версии v2 → блок плана (без умолчаний: снимок нормализован при сохранении)."""
    block: dict[str, Any] = {
        "kind": raw["kind"],
        "prep_seconds": int(raw.get("prep_seconds") or 0),
        "rest_after_block_seconds": raw.get("rest_after_block_seconds"),
        "extra_sets_allowed": bool(raw.get("extra_sets_allowed", raw["kind"] == BLOCK_SETS)),
    }
    if raw["kind"] == BLOCK_INTERVAL:
        interval = raw["interval"]
        block["interval"] = {
            "work_seconds": int(interval["work_seconds"]), "rest_seconds": int(interval["rest_seconds"]),
            "rounds": int(interval["rounds"]), "record_reps_per_round": bool(interval.get("record_reps_per_round")),
        }
        block["extra_sets_allowed"] = False
    else:
        sets = [_set_from_snapshot(s) for s in raw["sets"]]
        sets[-1]["rest_after_seconds"] = None  # W4
        block["sets"] = sets
    return block


@dataclass(frozen=True)
class FallbackTarget:
    metric: str  # "reps" | "time"
    value: int
    is_max_set: bool = False


@dataclass(frozen=True)
class FallbackInterval:
    work_seconds: int
    rest_seconds: int
    total_duration_seconds: int


def _fallback_set_kind(target: FallbackTarget) -> tuple[str, int | None]:
    if target.metric == "time":
        if target.is_max_set or target.value <= 0:
            return SET_MAX_TIME, None
        return SET_TIME, target.value
    if target.is_max_set or target.value <= 0:
        return SET_MAX_REPS, None
    return SET_REPS, target.value


def fallback_block(
    targets: Sequence[FallbackTarget], *, rest_seconds: int | None, interval: FallbackInterval | None,
    is_first_block: bool,
) -> dict[str, Any]:
    """Блок без снимка версии: цели сессии + умолчания контракта (докстринг модуля)."""
    if interval is not None:
        cycle = interval.work_seconds + interval.rest_seconds
        rounds = max(1, interval.total_duration_seconds // cycle) if cycle > 0 else 1
        return {
            "kind": BLOCK_INTERVAL, "prep_seconds": DEFAULT_PREP_SECONDS,
            "rest_after_block_seconds": DEFAULT_BLOCK_REST_SECONDS, "extra_sets_allowed": False,
            "interval": {
                "work_seconds": interval.work_seconds, "rest_seconds": interval.rest_seconds, "rounds": rounds,
                "record_reps_per_round": False,
            },
        }
    rest = SYSTEM_DEFAULT_REST_SECONDS if rest_seconds is None else rest_seconds
    sets = []
    for target in targets or (FallbackTarget("reps", 0, True),):
        kind, value = _fallback_set_kind(target)
        sets.append({"kind": kind, "target": value, "rest_after_seconds": rest})
    sets[-1]["rest_after_seconds"] = None
    timed_start = sets[0]["kind"] in (SET_TIME, SET_MAX_TIME)
    return {
        "kind": BLOCK_SETS,
        "prep_seconds": DEFAULT_PREP_SECONDS if is_first_block or timed_start else 0,
        "rest_after_block_seconds": DEFAULT_BLOCK_REST_SECONDS, "extra_sets_allowed": True, "sets": sets,
    }


def finalize_plan(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Последний блок без отдыха после себя (W-контракт); проверка инвариантов движка."""
    if blocks:
        blocks[-1]["rest_after_block_seconds"] = None
    plan = {"blocks": blocks}
    validate_plan(plan)
    return plan


def snapshot_is_executable(snapshot: Mapping[str, Any] | None) -> bool:
    """Снимок версии v2 (не синтезированный) с конкретными подходами/интервалом у каждого блока."""
    if not snapshot or snapshot.get("synthesized"):
        return False
    blocks = snapshot.get("blocks") or []
    if not blocks:
        return False
    for block in blocks:
        if block.get("kind") == BLOCK_INTERVAL and not block.get("interval"):
            return False
        if block.get("kind") == BLOCK_SETS and not block.get("sets"):
            return False
    return True
