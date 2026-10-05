import assert from "node:assert/strict";
import { test } from "node:test";

import {
  initialLocalSession, isLocalSessionReusable, localPhaseEndsAtMs, type LocalLiveSession,
} from "../src/offlineSession.ts";
import type { LiveSessionResponse } from "../src/apiV2.ts";

const ENDS_AT = "2026-01-01T10:01:00.000Z";

function serverSession(overrides: Partial<LiveSessionResponse> = {}): LiveSessionResponse {
  return {
    id: 7,
    client_session_id: "client-7",
    status: "started",
    phase: { name: "rest", ends_at: ENDS_AT },
    phase_index: 4,
    current_block_index: 0,
    current_set_number: 1,
    blocks: [{ rest_seconds: 60, targets: [{}, {}, {}], set_logs: [{}] }],
    awaiting_block_start: false,
    ...overrides,
  } as unknown as LiveSessionResponse;
}

test("rest timer after reload is reconciled from server ends_at, not restarted", () => {
  const server = serverSession();
  const reloaded = initialLocalSession("client-7", server);
  // "Вход в локальную фазу" = момент перезагрузки, строго позже ends_at − 60 с:
  // если бы таймер считался от него, остаток снова стал бы полной минутой.
  assert.equal(localPhaseEndsAtMs(reloaded), new Date(ENDS_AT).getTime());
});

test("unsynced optimistic phase uses local entered-at + duration", () => {
  const local: LocalLiveSession = {
    ...initialLocalSession("client-7", serverSession()),
    pendingPhaseAdvances: 1,
    localPhase: { phaseName: "rest", blockIndex: 0, setNumber: 1 },
    localPhaseEnteredAt: "2026-01-01T10:00:00.000Z",
  };
  assert.equal(localPhaseEndsAtMs(local), new Date("2026-01-01T10:01:00.000Z").getTime());
});

test("phases without a timer have no end", () => {
  const server = serverSession({ phase: { name: "go", ends_at: null } as LiveSessionResponse["phase"] });
  assert.equal(localPhaseEndsAtMs(initialLocalSession("client-7", server)), null);
});

test("recovery keeps logged sets: next set index continues after server logs", () => {
  const server = serverSession({
    blocks: [
      { rest_seconds: 60, targets: [{}, {}, {}], set_logs: [{}, {}] },
      { rest_seconds: 60, targets: [{}], set_logs: [{}] },
    ] as unknown as LiveSessionResponse["blocks"],
  });
  const local = initialLocalSession("client-7", server);
  assert.equal(local.nextSetIndex, 3);
  assert.deepEqual(local.pendingSets, []);
});

test("saved draft is reused for the same session (pending sets survive), dropped for another", () => {
  const server = serverSession();
  const draft: LocalLiveSession = {
    ...initialLocalSession("client-7", server),
    pendingSets: [{ setIndex: 1, blockIndex: 0, exerciseId: 1, value: "8" }],
    server: serverSession({ phase_index: 2 }),
  };
  assert.equal(isLocalSessionReusable(draft, server), true);
  assert.equal(isLocalSessionReusable({ ...draft, serverSessionId: 8 }, server), false);
  assert.equal(isLocalSessionReusable(null, server), false);
});
