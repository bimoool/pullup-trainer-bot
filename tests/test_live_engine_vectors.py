"""Общие JSON-векторы Live Engine v2 (issue #306, LIVE_ENGINE_V2 §2 C3): ровно тот же файл
``contracts/live_engine_vectors.json`` прогоняет vitest (webapp-frontend/tests/liveEngineVectors.test.ts) —
одна интерпретация переходов на сервере и в клиенте."""

import copy
import json
from pathlib import Path

import pytest

from app.domain import live_engine as engine

VECTORS = json.loads((Path(__file__).resolve().parents[1] / "contracts" / "live_engine_vectors.json").read_text())


def _subset(actual, expected, path="$"):
    """Глубокое сравнение-подмножество: у объектов — только перечисленные ключи, массивы — точно по
    длине и порядку (тот же алгоритм в TS-раннере)."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected object, got {actual!r}"
        for key, value in expected.items():
            assert key in actual, f"{path}.{key}: missing"
            _subset(actual[key], value, f"{path}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list), f"{path}: expected array, got {actual!r}"
        assert len(actual) == len(expected), f"{path}: length {len(actual)} != {len(expected)}: {actual!r}"
        for index, (a, e) in enumerate(zip(actual, expected, strict=True)):
            _subset(a, e, f"{path}[{index}]")
    else:
        assert actual == expected, f"{path}: {actual!r} != {expected!r}"


def run_case(case):
    plan = VECTORS["plans"][case["plan"]]
    state, _ = engine.start(plan, case["start_at"])
    if "start_expect" in case:
        _subset(state, case["start_expect"], "start")
    log = [{"type": engine.EV_START, "at": case["start_at"], "payload": {}}]
    for index, step in enumerate(case["steps"]):
        where = f"step[{index}] {step['op']}"
        before = copy.deepcopy(state)
        events, effects = [], []
        if step["op"] == "apply":
            state, events, effects = engine.apply_event(plan, state, step["event"], step["at"])
            assert before == copy.deepcopy(before)  # вход не мутирован (сравнение с копией до вызова)
            log.extend({"type": e["type"], "at": e["at"], "payload": {}} for e in events)
            log.append({"type": step["event"]["type"], "at": step["at"], "payload": step["event"].get("payload", {})})
        elif step["op"] == "advance":
            state, effects = engine.advance(plan, state, step["event"], step["at"])
            log.append({"type": step["event"]["type"], "at": step["at"], "payload": step["event"].get("payload", {})})
        elif step["op"] == "project":
            state, events, effects = engine.project(plan, state, step["now"])
            log.extend({"type": e["type"], "at": e["at"], "payload": {}} for e in events)
        elif step["op"] == "timeline":
            _subset(engine.timeline(plan, state), step["expect"], where)
            continue
        else:
            raise AssertionError(f"unknown op {step['op']}")
        if "expect" in step:
            _subset(state, step["expect"], where)
        if "expect_events" in step:
            _subset(events, step["expect_events"], f"{where} events")
        if "expect_effects" in step:
            _subset(effects, step["expect_effects"], f"{where} effects")
    if case.get("rebuild"):
        assert engine.rebuild(plan, log) == state, "rebuild(events) != live state"
    return state


@pytest.mark.parametrize("case", VECTORS["cases"], ids=[c["name"] for c in VECTORS["cases"]])
def test_vector(case):
    run_case(case)


@pytest.mark.parametrize("case", VECTORS["clamp"], ids=[c["name"] for c in VECTORS["clamp"]])
def test_clamp_vector(case):
    assert engine.clamp_client_at(case["client_at"], case["last_at"], case["now"]) == case["expect"]


def test_advance_is_pure():
    plan = VECTORS["plans"]["basic"]
    state, _ = engine.start(plan, 0)
    frozen = copy.deepcopy(state)
    engine.advance(plan, state, {"type": "skip_wait", "payload": {"phase_seq": 0}}, 1000)
    engine.project(plan, state, 10**9)
    assert state == frozen


def test_vectors_cover_required_scenarios():
    """Требование задачи: векторы покрывают обычную тренировку, несколько подходов/блоков, дедлайны
    отдыха, skip_wait, паузу, фон, дубль, устаревшее событие, интервал, extra set, правку, досрочное
    завершение."""
    names = " ".join(case["name"] for case in VECTORS["cases"]).lower()
    for needle in (
        "basic normal", "multiple blocks", "skip_wait", "pause", "background", "duplicate", "stale",
        "interval", "extra set", "correct_previous", "finish_early", "cancel", "timeline",
    ):
        assert needle in names, needle
