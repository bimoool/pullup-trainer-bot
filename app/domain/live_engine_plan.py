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


def _explicit_seconds(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def fallback_block(
    targets: Sequence[FallbackTarget], *, rest_seconds: int | None, interval: FallbackInterval | None,
    is_first_block: bool, set_rests: Sequence[Any] | None = None, block_rest_seconds: Any = None,
) -> dict[str, Any]:
    """Блок без снимка версии: цели сессии + умолчания контракта (докстринг модуля).

    set_rests / block_rest_seconds — явный отдых из снимка сессии (рецепт курса V5.6, #305: 240/30 → 900 → 180).
    Явное значение всегда важнее умолчания (решение владельца #306 п. 5: умолчания — только при отсутствии
    значения); None — значения нет, действует умолчание."""
    block_rest = _explicit_seconds(block_rest_seconds)
    block_rest = DEFAULT_BLOCK_REST_SECONDS if block_rest is None else block_rest
    if interval is not None:
        cycle = interval.work_seconds + interval.rest_seconds
        # Раунды = число фаз работы, НАЧАТЫХ за общее время V1 (у V1 15 с при 5/5 — две работы: 0–5, 10–15);
        # кратное время (норма v2, WORKOUT §8) даёт ровно total / (work + rest).
        rounds = max(1, -(-interval.total_duration_seconds // cycle)) if cycle > 0 else 1
        return {
            "kind": BLOCK_INTERVAL, "prep_seconds": DEFAULT_PREP_SECONDS,
            "rest_after_block_seconds": block_rest, "extra_sets_allowed": False,
            "interval": {
                "work_seconds": interval.work_seconds, "rest_seconds": interval.rest_seconds, "rounds": rounds,
                "record_reps_per_round": False,
            },
        }
    rest = SYSTEM_DEFAULT_REST_SECONDS if rest_seconds is None else rest_seconds
    explicit = list(set_rests) if set_rests is not None and len(set_rests) == len(targets) else None
    sets = []
    for index, target in enumerate(targets or (FallbackTarget("reps", 0, True),)):
        kind, value = _fallback_set_kind(target)
        own = _explicit_seconds(explicit[index]) if explicit is not None and index < len(explicit) else None
        sets.append({"kind": kind, "target": value, "rest_after_seconds": rest if own is None else own})
    sets[-1]["rest_after_seconds"] = None
    timed_start = sets[0]["kind"] in (SET_TIME, SET_MAX_TIME)
    return {
        "kind": BLOCK_SETS,
        "prep_seconds": DEFAULT_PREP_SECONDS if is_first_block or timed_start else 0,
        "rest_after_block_seconds": block_rest, "extra_sets_allowed": True, "sets": sets,
    }


def apply_course_rules(blocks: list[dict[str, Any]], course_blocks: Sequence[Mapping[str, Any]]) -> None:
    """Рецепт V5.6 из снимка сессии (#305) → правила плана движка: подтверждение техники/отдыха у каждого
    блока (§11), стоп-правило объёма B (§6) и отображение подходов — маркер, минимальная цель AMRAP p4
    (§5), потолок контрольного подхода (§7). Цели, отдых и подготовка не меняются; число блоков/подходов
    не совпало — план остаётся без правил (ничего не угадывается)."""
    if len(blocks) != len(course_blocks):
        return
    for block, course in zip(blocks, course_blocks, strict=True):
        sets = block.get("sets") or []
        course_sets = course.get("sets") or []
        if block["kind"] != BLOCK_SETS or len(sets) != len(course_sets):
            continue
        block["confirm_checks"] = True
        stop_rule = course.get("stop_rule") or {}
        if isinstance(stop_rule.get("stop_at_or_below"), int):
            block["stop_at_or_below"] = stop_rule["stop_at_or_below"]
        for plan_set, course_set in zip(sets, course_sets, strict=True):
            plan_set["marker"] = course_set.get("marker")
            if course_set.get("marker") == "amrap":
                plan_set["min_target"] = course_set.get("target_reps")
            if course_set.get("cap_reps") is not None:
                plan_set["cap"] = course_set["cap_reps"]


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
