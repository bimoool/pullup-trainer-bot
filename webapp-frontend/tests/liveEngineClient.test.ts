import assert from "node:assert/strict";
import { test } from "node:test";

import { remainingMs, start, type EnginePlan } from "../src/liveEngine.ts";
import { displayState, dropAcknowledged, emptyQueue, serverOffsetMs } from "../src/liveEngineClient.ts";

const PLAN: EnginePlan = {
  blocks: [{
    kind: "sets", prep_seconds: 5, rest_after_block_seconds: null, extra_sets_allowed: true,
    sets: [
      { kind: "reps", target: 10, rest_after_seconds: 60 },
      { kind: "reps", target: 10, rest_after_seconds: null },
    ],
  }],
};

test("serverOffsetMs: server_time против середины запроса", () => {
  assert.equal(serverOffsetMs(10_500, 1_000, 2_000), 9_000);
  assert.equal(serverOffsetMs(1_000, 1_000, 1_000), 0);
});

test("displayState: без очереди — проекция серверного состояния по единственному дедлайну (C1)", () => {
  const [server] = start(PLAN, 0);
  assert.equal(displayState(PLAN, server, [], 4_999).phase, "PREP");
  const atDeadline = displayState(PLAN, server, [], 5_000);
  assert.equal(atDeadline.phase, "WORK");
  assert.equal(remainingMs(server, 2_000), 3_000);
});

test("displayState: неподтверждённые события применяются тем же шагом, что на сервере", () => {
  const [server] = start(PLAN, 0);
  const submit = {
    client_event_id: "a", type: "submit_result", client_at_ms: 20_000,
    payload: { block_index: 0, set_index: 0, round_index: null, value: 10 },
  };
  const rest = displayState(PLAN, server, [submit], 30_000);
  assert.equal(rest.phase, "REST");
  assert.equal(rest.phase_deadline_at, 80_000);
  // фон поперёк конца отдыха: на возврате уже WORK следующего подхода
  const back = displayState(PLAN, server, [submit], 90_000);
  assert.equal(back.phase, "WORK");
  assert.equal(back.cursor.set_index, 1);
  // пауза — тоже событие: остаток заморожен
  const pause = { client_event_id: "b", type: "pause", client_at_ms: 50_000, payload: { phase_seq: 2 } };
  const paused = displayState(PLAN, server, [submit, pause], 500_000);
  assert.equal(paused.phase, "REST");
  assert.equal(remainingMs(paused, 500_000), 30_000);
});

test("dropAcknowledged: из очереди уходит только учтённое сервером", () => {
  const queue = {
    ...emptyQueue(7),
    events: [
      { client_event_id: "a", type: "pause", payload: {}, client_at_ms: 1 },
      { client_event_id: "b", type: "resume", payload: {}, client_at_ms: 2 },
    ],
  };
  assert.deepEqual(dropAcknowledged(queue, ["a"]).events.map((e) => e.client_event_id), ["b"]);
});
