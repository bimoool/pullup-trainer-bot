/**
 * Общие JSON-векторы Live Engine v2 (issue #306, LIVE_ENGINE_V2 §2 C3): ровно тот же файл
 * contracts/live_engine_vectors.json, что прогоняет pytest (tests/test_live_engine_vectors.py) —
 * TypeScript-зеркало обязано давать те же переходы.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, test } from "vitest";

import {
  advance, applyEvent, clampClientAt, project, rebuild, start, timeline,
  type EngineEvent, type EnginePlan, type EngineState, type Payload,
} from "../src/liveEngine.ts";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Json = any;

const VECTORS: Json = JSON.parse(readFileSync(resolve(__dirname, "../../contracts/live_engine_vectors.json"), "utf8"));

/** Глубокое сравнение-подмножество — тот же алгоритм, что _subset в pytest-раннере. */
function subset(actual: Json, expected: Json, path = "$"): void {
  if (expected !== null && typeof expected === "object" && !Array.isArray(expected)) {
    expect(actual !== null && typeof actual === "object" && !Array.isArray(actual), `${path}: expected object`).toBe(true);
    for (const [key, value] of Object.entries(expected)) {
      expect(key in actual, `${path}.${key}: missing`).toBe(true);
      subset(actual[key], value, `${path}.${key}`);
    }
  } else if (Array.isArray(expected)) {
    expect(Array.isArray(actual), `${path}: expected array`).toBe(true);
    expect(actual.length, `${path}: length ${JSON.stringify(actual)}`).toBe(expected.length);
    expected.forEach((item: Json, index: number) => subset(actual[index], item, `${path}[${index}]`));
  } else {
    expect(actual, path).toEqual(expected);
  }
}

function runCase(testCase: Json): EngineState {
  const plan: EnginePlan = VECTORS.plans[testCase.plan];
  let [state] = start(plan, testCase.start_at);
  if (testCase.start_expect) {
    subset(state, testCase.start_expect, "start");
  }
  const log: { type: string; at: number; payload?: Payload }[] = [{ type: "start", at: testCase.start_at, payload: {} }];
  testCase.steps.forEach((step: Json, index: number) => {
    const where = `step[${index}] ${step.op}`;
    let events: Json[] = [];
    let effects: Json[] = [];
    if (step.op === "apply") {
      const before = JSON.stringify(state);
      const result = applyEvent(plan, state, step.event as EngineEvent, step.at);
      expect(JSON.stringify(state), `${where}: input mutated`).toBe(before);
      [state, events, effects] = result;
      log.push(...events.map((e) => ({ type: e.type, at: e.at, payload: {} })));
      log.push({ type: step.event.type, at: step.at, payload: step.event.payload ?? {} });
    } else if (step.op === "advance") {
      [state, effects] = advance(plan, state, step.event as EngineEvent, step.at);
      log.push({ type: step.event.type, at: step.at, payload: step.event.payload ?? {} });
    } else if (step.op === "project") {
      [state, events, effects] = project(plan, state, step.now);
      log.push(...events.map((e) => ({ type: e.type, at: e.at, payload: {} })));
    } else if (step.op === "timeline") {
      subset(timeline(plan, state), step.expect, where);
      return;
    } else {
      throw new Error(`unknown op ${step.op}`);
    }
    if (step.expect !== undefined) {
      subset(state, step.expect, where);
    }
    if (step.expect_events !== undefined) {
      subset(events, step.expect_events, `${where} events`);
    }
    if (step.expect_effects !== undefined) {
      subset(effects, step.expect_effects, `${where} effects`);
    }
  });
  if (testCase.rebuild) {
    expect(rebuild(plan, log), "rebuild(events) != live state").toEqual(state);
  }
  return state;
}

describe("Live Engine v2 shared vectors", () => {
  for (const testCase of VECTORS.cases) {
    test(testCase.name, () => {
      runCase(testCase);
    });
  }
  for (const clampCase of VECTORS.clamp) {
    test(`clamp: ${clampCase.name}`, () => {
      expect(clampClientAt(clampCase.client_at, clampCase.last_at, clampCase.now)).toBe(clampCase.expect);
    });
  }
});
