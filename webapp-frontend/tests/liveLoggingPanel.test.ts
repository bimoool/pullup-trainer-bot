import assert from "node:assert/strict";
import { test } from "node:test";

import {
  editLastLoggedSet, initialLocalSession, isGetReadyCueActive, rebaseLocalSession, restPanelExpandedByDefault,
  type LocalLiveSession, type QueuedSet,
} from "../src/offlineSession.ts";
import type { LiveSessionResponse } from "../src/apiV2.ts";

function server(): LiveSessionResponse {
  return {
    id: 7, client_session_id: "c7", status: "started",
    phase: { name: "rest", ends_at: null },
    phase_index: 4, current_block_index: 0, current_set_number: 1,
    blocks: [{ exercise_id: 3, protocol_type: "reps_sets", rest_seconds: 60, targets: [{}, {}], set_logs: [] }],
    awaiting_block_start: false,
  } as unknown as LiveSessionResponse;
}

const LOGGED: QueuedSet = { setIndex: 0, blockIndex: 0, exerciseId: 3, value: "8", effort: null, note: null };

function restLocal(pending: QueuedSet[]): LocalLiveSession {
  return { ...initialLocalSession("c7", server()), nextSetIndex: 1, pendingSets: pending, lastLogged: LOGGED };
}

test("rest panel expands by default only for rest of 20 s or more", () => {
  assert.equal(restPanelExpandedByDefault(19), false);
  assert.equal(restPanelExpandedByDefault(20), true);
  assert.equal(restPanelExpandedByDefault(60), true);
  assert.equal(restPanelExpandedByDefault(2), false);
  assert.equal(restPanelExpandedByDefault(null), true); // default rest is 90 s
});

test("get-ready cue shows only during the last 10 s of rest", () => {
  assert.equal(isGetReadyCueActive("rest", 10), true);
  assert.equal(isGetReadyCueActive("rest", 0), true);
  assert.equal(isGetReadyCueActive("rest", 10.5), false);
  assert.equal(isGetReadyCueActive("rest", 45), false);
  assert.equal(isGetReadyCueActive("rest", null), false);
  assert.equal(isGetReadyCueActive("go", 3), false);
  assert.equal(isGetReadyCueActive("get_ready", 3), false);
});

test("editing the last set replaces its queued entry — same set_index, no duplicate", () => {
  const edited = editLastLoggedSet(restLocal([LOGGED]), { value: " 9 ", effort: "3", note: " ok " });
  assert.equal(edited.pendingSets.length, 1);
  assert.deepEqual(edited.pendingSets[0], { ...LOGGED, value: "9", effort: "3", note: "ok" });
  assert.deepEqual(edited.lastLogged, edited.pendingSets[0]);
});

test("editing an already synced set re-queues the same set_index", () => {
  const edited = editLastLoggedSet(restLocal([]), { value: "9", effort: null, note: "" });
  assert.equal(edited.pendingSets.length, 1);
  assert.equal(edited.pendingSets[0].setIndex, LOGGED.setIndex);
  assert.equal(edited.pendingSets[0].value, "9");
});

test("empty value, unchanged values and a missing last set are no-ops", () => {
  const local = restLocal([LOGGED]);
  assert.equal(editLastLoggedSet(local, { value: "  ", effort: null, note: null }), local);
  assert.equal(editLastLoggedSet(local, { value: "8", effort: null, note: "" }), local);
  const none = { ...local, lastLogged: null };
  assert.equal(editLastLoggedSet(none, { value: "9", effort: null, note: null }), none);
});

test("rebase keeps an edit made while the original set was being flushed", () => {
  const flushed = restLocal([LOGGED]);
  const current = editLastLoggedSet(flushed, { value: "9", effort: "2", note: null });
  const rebased = rebaseLocalSession(flushed, current, server());
  assert.equal(rebased.pendingSets.length, 1);
  assert.equal(rebased.pendingSets[0].value, "9");
  assert.equal(rebased.lastLogged?.value, "9");
});

test("rebase drops a flushed set that was not edited", () => {
  const flushed = restLocal([LOGGED]);
  const rebased = rebaseLocalSession(flushed, flushed, server());
  assert.equal(rebased.pendingSets.length, 0);
  assert.equal(rebased.lastLogged?.value, "8");
});
