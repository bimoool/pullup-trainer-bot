import assert from "node:assert/strict";
import { test } from "node:test";

import { canGoBackLocal, initialLocalSession, recordedPlanSet, type LocalLiveSession } from "../src/offlineSession.ts";
import type { LiveSessionResponse } from "../src/apiV2.ts";

function local(phase: string, setNumber: number, logs: unknown[] = []): LocalLiveSession {
  const server = {
    id: 7, client_session_id: "c7", status: "started",
    phase: { name: phase, ends_at: null }, phase_index: 4, current_block_index: 0, current_set_number: setNumber,
    blocks: [{ exercise_id: 3, protocol_type: "reps_sets", rest_seconds: 60, targets: [{}, {}, {}], set_logs: logs }],
    awaiting_block_start: false,
  } as unknown as LiveSessionResponse;
  return initialLocalSession("c7", server);
}

test("back: online + empty queue only; first set of the block is a boundary (#292)", () => {
  assert.equal(canGoBackLocal(local("rest", 1), true, false), true);
  assert.equal(canGoBackLocal(local("done", 3), true, false), true);
  assert.equal(canGoBackLocal(local("get_ready", 2), true, false), true);
  assert.equal(canGoBackLocal(local("go", 2), true, false), true);
  assert.equal(canGoBackLocal(local("get_ready", 1), true, false), false);
  assert.equal(canGoBackLocal(local("go", 1), true, false), false);
  assert.equal(canGoBackLocal(local("between", 1), true, false), false);
});

test("back is disabled offline, while syncing, with queued sets/advances or a queued finish", () => {
  const rest = local("rest", 1);
  assert.equal(canGoBackLocal(rest, false, false), false);
  assert.equal(canGoBackLocal(rest, true, true), false);
  assert.equal(canGoBackLocal({ ...rest, pendingPhaseAdvances: 1 }, true, false), false);
  const queued = { setIndex: 0, blockIndex: 0, exerciseId: 3, value: "8" };
  assert.equal(canGoBackLocal({ ...rest, pendingSets: [queued] }, true, false), false);
  assert.equal(canGoBackLocal({ ...rest, completeRequested: { abandoned: false } }, true, false), false);
});

test("recordedPlanSet returns the server set_index of a plan set, ignores extras and missing keys", () => {
  const logs = [
    { set_number: 1, set_index: 0, value: "8.00", effort: "3.0", note: "ok", is_extra: false },
    { set_number: 2, set_index: 5, value: "9.00", effort: null, note: null, is_extra: true },
    { set_number: 3, value: "7.00", effort: null, note: null, is_extra: false },
  ];
  const l = local("go", 1, logs);
  assert.deepEqual(recordedPlanSet(l, 0, 1), { setIndex: 0, value: "8", effort: "3", note: "ok" });
  assert.equal(recordedPlanSet(l, 0, 2), null);
  assert.equal(recordedPlanSet(l, 0, 3), null);
  assert.equal(recordedPlanSet(l, 1, 1), null);
});
