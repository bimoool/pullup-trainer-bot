import assert from "node:assert/strict";
import { test } from "node:test";
import { applyEvent, start, type EnginePlan } from "../src/liveEngine.ts";

test("B: all ten ordinary five-rep sets have 60s rest; 900s only after the tenth", () => {
  const plan: EnginePlan = { blocks: [
    { kind: "sets", prep_seconds: 0, rest_after_block_seconds: 900, stop_at_or_below: 2,
      sets: Array.from({ length: 10 }, (_, i) => ({ kind: "reps", target: 5, rest_after_seconds: i < 9 ? 60 : null })) },
    { kind: "sets", prep_seconds: 0, rest_after_block_seconds: null,
      sets: [{ kind: "reps", target: 3, rest_after_seconds: null }] },
  ] };
  let [state] = start(plan, 0);
  let at = 0;
  for (let index = 0; index < 10; index++) {
    assert.equal(state.phase, "WORK");
    assert.equal(state.cursor.set_index, index);
    [state] = applyEvent(plan, state, { type: "submit_result", payload: {
      block_index: 0, set_index: index, round_index: null, value: 5,
    } }, at += 1000);
    assert.equal(state.phase, "REST");
    assert.equal(state.rest_kind, index < 9 ? "set" : "block");
    assert.equal(state.phase_duration_ms, (index < 9 ? 60 : 900) * 1000);
    [state] = applyEvent(plan, state, { type: "skip_wait", payload: { phase_seq: state.phase_seq } }, at += 1000);
  }
  assert.equal(state.cursor.block_index, 1);
  assert.equal(state.logs.length, 10);
});
