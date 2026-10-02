import assert from "node:assert/strict";
import { test } from "node:test";

import {
  canPauseLocal, clearPauseState, extraSetBlockIndex, initialLocalSession, isLocalPaused, localPhaseEndsAtMs,
  pauseLocalSession, rebaseLocalSession, resumeLocalSession,
} from "../src/offlineSession.ts";
import type { LiveSessionResponse } from "../src/apiV2.ts";

const T0 = Date.parse("2026-01-01T10:00:00.000Z");

function server(overrides: Partial<LiveSessionResponse> = {}): LiveSessionResponse {
  return {
    id: 7, client_session_id: "c7", status: "started",
    phase: { name: "rest", ends_at: new Date(T0 + 60_000).toISOString() },
    phase_index: 4, current_block_index: 0, current_set_number: 1,
    blocks: [{ exercise_id: 3, protocol_type: "reps_sets", rest_seconds: 60, targets: [{}, {}], set_logs: [] }],
    awaiting_block_start: false,
    ...overrides,
  } as unknown as LiveSessionResponse;
}

test("pause freezes the remaining time and resume restarts from it", () => {
  const local = initialLocalSession("c7", server());
  const paused = pauseLocalSession(local, T0 + 20_000);
  assert.equal(isLocalPaused(paused), true);
  assert.equal(paused.pausedRemainingMs, 40_000);
  assert.equal(localPhaseEndsAtMs(paused), null);

  const resumed = resumeLocalSession(paused, T0 + 500_000);
  assert.equal(isLocalPaused(resumed), false);
  assert.equal(localPhaseEndsAtMs(resumed), T0 + 540_000);
});

test("pause survives a snapshot round trip and server rebase of the same phase", () => {
  const paused = pauseLocalSession(initialLocalSession("c7", server()), T0 + 10_000);
  const reloaded = JSON.parse(JSON.stringify(paused));
  assert.equal(reloaded.pausedRemainingMs, 50_000);
  const rebased = rebaseLocalSession(reloaded, reloaded, server());
  assert.equal(rebased.pausedRemainingMs, 50_000);
});

test("rebase onto a different server phase drops the pause", () => {
  const paused = pauseLocalSession(initialLocalSession("c7", server()), T0 + 10_000);
  const rebased = rebaseLocalSession(paused, paused, server({ phase_index: 5, phase: { name: "get_ready", ends_at: null } }));
  assert.equal(isLocalPaused(rebased), false);
  assert.equal(rebased.endsAtOverride ?? null, null);
});

test("pause only on get_ready/rest countdowns", () => {
  const rest = initialLocalSession("c7", server());
  assert.equal(canPauseLocal(rest), true);
  const go = initialLocalSession("c7", server({ phase: { name: "go", ends_at: null } }));
  assert.equal(canPauseLocal(go), false);
  assert.equal(pauseLocalSession(go, T0), go);
  assert.equal(isLocalPaused(clearPauseState(pauseLocalSession(rest, T0))), false);
});

test("extra set is offered only after the block is finished and never for interval", () => {
  const go = initialLocalSession("c7", server({ phase: { name: "go", ends_at: null } }));
  assert.equal(extraSetBlockIndex(go), null);
  const done = { ...go, localPhase: { phaseName: "done" as const, blockIndex: 0, setNumber: 2 } };
  assert.equal(extraSetBlockIndex(done), 0);
  const between = { ...go, localPhase: { phaseName: "between" as const, blockIndex: 1, setNumber: 1 } };
  assert.equal(extraSetBlockIndex(between), 0); // между блоками — завершённый предыдущий
  const interval = initialLocalSession("c7", server({
    blocks: [{ exercise_id: 3, protocol_type: "interval", targets: [], set_logs: [] }] as never,
  }));
  assert.equal(extraSetBlockIndex({ ...interval, localPhase: { phaseName: "done", blockIndex: 0, setNumber: 1 } }), null);
});
