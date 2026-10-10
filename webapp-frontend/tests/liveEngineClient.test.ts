import assert from "node:assert/strict";
import { test } from "node:test";

import { remainingMs, start, type EnginePlan } from "../src/liveEngine.ts";
import {
  clearQueue, displayState, drainEngineQueues, dropAcknowledged, emptyQueue, loadAllQueues, loadQueue, saveQueue,
  serverOffsetMs, type DrainApi, type EngineQueue, type QueueStore,
} from "../src/liveEngineClient.ts";

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

// --- #306 B1: очереди по сессиям и досылка без экрана тренировки ----------------------------------

function memoryStore(initial: Record<string, EngineQueue> = {}): QueueStore & { data: Map<string, EngineQueue> } {
  const data = new Map<string, EngineQueue>(Object.entries(initial));
  return {
    data,
    get: async (key) => data.get(key),
    set: async (key, value) => void data.set(key, structuredClone(value)),
    del: async (key) => void data.delete(key),
    keys: async () => [...data.keys()],
  };
}

type Call = { kind: "events"; sessionId: number; ids: string[] } | { kind: "complete"; sessionId: number; review: unknown };

function fakeApi(behaviour: { events?: (sessionId: number, ids: string[]) => unknown; complete?: (sessionId: number) => unknown } = {}) {
  const calls: Call[] = [];
  const api: DrainApi = {
    postEvents: (async (_init: string, sessionId: number, events: { client_event_id: string }[]) => {
      const ids = events.map((e) => e.client_event_id);
      calls.push({ kind: "events", sessionId, ids });
      const custom = behaviour.events?.(sessionId, ids);
      if (custom instanceof Error) {
        throw custom;
      }
      return custom ?? { engine_status: "active", event_results: ids.map((id) => ({ client_event_id: id, outcome: "applied" })) };
    }) as unknown as DrainApi["postEvents"],
    complete: (async (_init: string, sessionId: number, _abandoned: boolean, review: unknown) => {
      calls.push({ kind: "complete", sessionId, review });
      const custom = behaviour.complete?.(sessionId);
      if (custom instanceof Error) {
        throw custom;
      }
      return { status: "completed" };
    }) as unknown as DrainApi["complete"],
  };
  return { api, calls };
}

const stop = (id: string, at = 20_000) => ({ client_event_id: id, type: "stop", payload: { phase_seq: 1 }, client_at_ms: at });
const httpError = (status: number) => Object.assign(new Error(`HTTP ${status}`), { status });

test("drain: офлайн-события уходят и очередь снимается после подтверждения", async () => {
  const store = memoryStore();
  await saveQueue({ ...emptyQueue(11), events: [stop("s1")] }, store);
  const { api, calls } = fakeApi();
  assert.deepEqual(await drainEngineQueues("init", store, api), { pending: false });
  assert.deepEqual(calls, [{ kind: "events", sessionId: 11, ids: ["s1"] }]);
  assert.equal(store.data.size, 0);
});

test("drain: нет очередей — ни одного запроса (обычный запуск без задержки)", async () => {
  const { api, calls } = fakeApi();
  assert.deepEqual(await drainEngineQueues("init", memoryStore(), api), { pending: false });
  assert.deepEqual(calls, []);
});

test("drain: оценка после авто-завершения сервером уходит complete-ом и без открытого экрана", async () => {
  const store = memoryStore();
  await saveQueue({ ...emptyQueue(12), complete: { effort: "4", comment: "тяжело" } }, store);
  const { api, calls } = fakeApi();
  assert.deepEqual(await drainEngineQueues("init", store, api), { pending: false });
  assert.deepEqual(calls, [{ kind: "complete", sessionId: 12, review: { effort: "4", comment: "тяжело" } }]);
  assert.equal(store.data.size, 0);
});

test("drain: события раньше оценки, в одном проходе", async () => {
  const store = memoryStore();
  await saveQueue({ ...emptyQueue(13), events: [stop("f1")], complete: { effort: null, comment: "ok" } }, store);
  const { api, calls } = fakeApi();
  await drainEngineQueues("init", store, api);
  assert.deepEqual(calls.map((c) => c.kind), ["events", "complete"]);
  assert.equal(store.data.size, 0);
});

test("очереди по сессиям: сессия B не затирает недосланное сессии A, A досылается отдельно", async () => {
  const store = memoryStore();
  await saveQueue({ ...emptyQueue(21), events: [stop("a1")], complete: { effort: "3", comment: null } }, store);
  await saveQueue({ ...emptyQueue(22), events: [stop("b1")] }, store);  // старт/событие сессии B
  assert.deepEqual((await loadQueue(21, store)).events.map((e) => e.client_event_id), ["a1"]);
  assert.deepEqual((await loadQueue(22, store)).events.map((e) => e.client_event_id), ["b1"]);
  await clearQueue(22, store);  // B завершилась на экране
  assert.equal((await loadQueue(21, store)).complete?.effort, "3");
  const { api, calls } = fakeApi();
  await drainEngineQueues("init", store, api);
  assert.deepEqual(calls, [
    { kind: "events", sessionId: 21, ids: ["a1"] },
    { kind: "complete", sessionId: 21, review: { effort: "3", comment: null } },
  ]);
});

test("очередь старого формата (один ключ) переезжает под ключ своей сессии, не теряется", async () => {
  const store = memoryStore({ "pullup:v2:live-engine-queue": { ...emptyQueue(31), events: [stop("old")] } });
  const queues = await loadAllQueues(store);
  assert.deepEqual(queues.map((q) => q.sessionId), [31]);
  assert.equal(store.data.has("pullup:v2:live-engine-queue"), false);
  assert.deepEqual((await loadQueue(31, store)).events.map((e) => e.client_event_id), ["old"]);
});

test("потерянный ответ: очередь цела, pending; повтор шлёт те же client_event_id, дубль — no-op", async () => {
  const store = memoryStore();
  await saveQueue({ ...emptyQueue(41), events: [stop("x1"), stop("x2", 21_000)] }, store);
  let first = true;
  const { api, calls } = fakeApi({
    events: (_id, ids) => {
      if (first) {
        first = false;
        return new TypeError("Failed to fetch");  // сервер применил, ответ потерян
      }
      return { engine_status: "active", event_results: ids.map((id) => ({ client_event_id: id, outcome: "duplicate" })) };
    },
  });
  assert.deepEqual(await drainEngineQueues("init", store, api), { pending: true });
  assert.equal(store.data.size, 1);
  assert.deepEqual(await drainEngineQueues("init", store, api), { pending: false });
  assert.deepEqual(calls.map((c) => (c.kind === "events" ? c.ids : [])), [["x1", "x2"], ["x1", "x2"]]);
  assert.equal(store.data.size, 0);
});

test("сервер 5xx/сеть на complete — оценка остаётся в очереди (pending)", async () => {
  const store = memoryStore();
  await saveQueue({ ...emptyQueue(51), complete: { effort: "2", comment: null } }, store);
  const { api } = fakeApi({ complete: () => httpError(503) });
  assert.deepEqual(await drainEngineQueues("init", store, api), { pending: true });
  assert.equal((await loadQueue(51, store)).complete?.effort, "2");
});

test("404/409 (сессии нет / не движок v2) — досылать некуда, очередь снимается; отмена — тоже", async () => {
  const store = memoryStore();
  await saveQueue({ ...emptyQueue(61), events: [stop("g1")] }, store);
  await saveQueue({ ...emptyQueue(62), events: [stop("g2")] }, store);
  await saveQueue({ ...emptyQueue(63), events: [{ client_event_id: "c", type: "cancel", payload: {}, client_at_ms: 1 }] }, store);
  const { api } = fakeApi({
    events: (sessionId, ids) => (sessionId === 61 ? httpError(404) : sessionId === 62 ? httpError(409)
      : { engine_status: "cancelled", event_results: ids.map((id) => ({ client_event_id: id, outcome: "applied" })) }),
  });
  assert.deepEqual(await drainEngineQueues("init", store, api), { pending: false });
  assert.equal(store.data.size, 0);
});

test("drain никогда не бросает: сбой IndexedDB не ломает запуск приложения", async () => {
  const broken: QueueStore = {
    get: async () => { throw new Error("IDB closed"); },
    set: async () => { throw new Error("IDB closed"); },
    del: async () => { throw new Error("IDB closed"); },
    keys: async () => { throw new Error("IDB closed"); },
  };
  const { api, calls } = fakeApi();
  assert.deepEqual(await drainEngineQueues("init", broken, api), { pending: false });
  assert.deepEqual(calls, []);
  const store = memoryStore();
  await saveQueue({ ...emptyQueue(71), events: [stop("d1")] }, store);
  store.set = async () => { throw new Error("quota"); };  // ответ получен, а записать остаток нельзя
  assert.deepEqual(await drainEngineQueues("init", store, api), { pending: true });
});
