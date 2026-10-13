import assert from "node:assert/strict";
import { test } from "node:test";

import {
  applyEvent, clampClientAt, project, remainingMs, start, type EngineEvent, type EnginePlan, type EngineState,
} from "../src/liveEngine.ts";
import { fetchActiveLiveSession, fetchSessions } from "../src/apiV2.ts";
import { awaitEngineReconciliation } from "../src/engineGate.ts";
import {
  claimQueue, clearQueue, createScreenLifecycle, createSyncRetry, displayState, drainEngineQueues, dropAcknowledged, emptyQueue, loadAllQueues, loadQueue,
  releaseQueue, saveQueue, serverOffsetMs, startEngineReconciliation, wakeEngineReconciliation, type DrainApi,
  type EngineQueue, type QueueStore,
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

// --- #306 F1: сверка с повторами и ворота для чтений с проекцией ------------------------------------

/** Чтение с проекцией (GET /active, список сессий) — так его делает apiV2.ts: сначала ворота. */
async function gatedRead(order: string[], name: string): Promise<void> {
  await awaitEngineReconciliation();
  order.push(name);
}

function scriptedApi(script: Record<number, (unknown | Error)[]>, order: string[]) {
  const attempts = new Map<number, number>();
  return fakeApi({
    events: (sessionId, ids) => {
      const n = attempts.get(sessionId) ?? 0;
      attempts.set(sessionId, n + 1);
      const step = script[sessionId]?.[n];
      if (step instanceof Error) {
        order.push(`events:${sessionId}:fail`);
        return step;
      }
      order.push(`events:${sessionId}:ok`);
      return step ?? { engine_status: "active", event_results: ids.map((id) => ({ client_event_id: id, outcome: "applied" })) };
    },
  });
}

test("F1: временный сбой первой досылки — повтор сам, без online; чтение с проекцией ждёт успеха", async () => {
  const store = memoryStore();
  await saveQueue({ ...emptyQueue(81), events: [stop("t1", 3_000)] }, store);
  const order: string[] = [];
  const { api } = scriptedApi({ 81: [new TypeError("Failed to fetch")] }, order);
  const done = startEngineReconciliation("init", { store, api, delaysMs: [5] });
  const read = gatedRead(order, "GET /active");  // App: возобновление активной сессии
  await done;
  await read;
  assert.deepEqual(order, ["events:81:fail", "events:81:ok", "GET /active"]);
  assert.equal(store.data.size, 0);
});

test("F1: Журнал, открытый во время повторов, не опережает очередь (список ждёт сверки)", async () => {
  const store = memoryStore();
  await saveQueue({ ...emptyQueue(82), events: [stop("j1", 3_000)] }, store);
  const order: string[] = [];
  const failure = Object.assign(new Error("HTTP 502"), { status: 502 });
  const { api } = scriptedApi({ 82: [failure, new TypeError("Failed to fetch")] }, order);
  const done = startEngineReconciliation("init", { store, api, delaysMs: [5, 5] });
  await new Promise((resolve) => setTimeout(resolve, 1));
  const journal = gatedRead(order, "GET /api/v2/sessions");  // пользователь открыл Журнал между повторами
  await Promise.all([done, journal]);
  assert.deepEqual(order, ["events:82:fail", "events:82:fail", "events:82:ok", "GET /api/v2/sessions"]);
});

test("F1: окончательный ответ (404/409) — без повторов, ворота открываются; иной 4xx — очередь цела, без повторов", async () => {
  const store = memoryStore();
  await saveQueue({ ...emptyQueue(83), events: [stop("g")] }, store);
  await saveQueue({ ...emptyQueue(84), events: [stop("r")] }, store);
  const order: string[] = [];
  const { api, calls } = scriptedApi({ 83: [httpError(404)], 84: [httpError(422)] }, order);
  await startEngineReconciliation("init", { store, api, delaysMs: [5] });
  await gatedRead(order, "read");
  assert.equal(calls.length, 2);  // по одной попытке: окончательные ответы не повторяются
  assert.equal(store.data.has("pullup:v2:live-engine-queue:83"), false);  // 404 — сессии нет, досылать некуда
  assert.equal(store.data.has("pullup:v2:live-engine-queue:84"), true);   // 422 — не выбрасывается молча
});

test("F1: очереди по сессиям — сбой одной не держит другую: B снята с первой попытки, A — после повтора", async () => {
  const store = memoryStore();
  await saveQueue({ ...emptyQueue(85), events: [stop("a")] }, store);
  await saveQueue({ ...emptyQueue(86), events: [stop("b")] }, store);
  const order: string[] = [];
  const { api } = scriptedApi({ 85: [new TypeError("Failed to fetch"), new TypeError("Failed to fetch")] }, order);
  let sawBClearedWhileAPending = false;
  const done = startEngineReconciliation("init", { store, api, delaysMs: [20, 20] });
  await new Promise((resolve) => setTimeout(resolve, 10));
  sawBClearedWhileAPending = !store.data.has("pullup:v2:live-engine-queue:86") && store.data.has("pullup:v2:live-engine-queue:85");
  await done;
  assert.equal(sawBClearedWhileAPending, true);
  assert.deepEqual(order, ["events:85:fail", "events:86:ok", "events:85:fail", "events:85:ok"]);
  assert.equal(store.data.size, 0);
});

test("F1: нет очередей — ни одного запроса, ворота открыты сразу (Журнал/Главная без задержки)", async () => {
  const order: string[] = [];
  const { api, calls } = fakeApi();
  const started = Date.now();
  await startEngineReconciliation("init", { store: memoryStore(), api });
  await gatedRead(order, "read");
  assert.deepEqual(calls, []);
  assert.deepEqual(order, ["read"]);
  assert.ok(Date.now() - started < 50);
});

test("F1: очередь сессии, открытой на экране, сверка App не трогает; после ухода с экрана — досылает", async () => {
  const store = memoryStore();
  await saveQueue({ ...emptyQueue(87), events: [stop("own")] }, store);
  const order: string[] = [];
  const { api, calls } = scriptedApi({}, order);
  claimQueue(87);
  await startEngineReconciliation("init", { store, api });
  assert.deepEqual(calls, []);
  assert.equal(store.data.size, 1);
  releaseQueue(87);
  await startEngineReconciliation("init", { store, api });
  assert.deepEqual(order, ["events:87:ok"]);
  assert.equal(store.data.size, 0);
});

test("F1: пауза между повторами ограничена и будится online/возвратом (без busy-loop)", async () => {
  const store = memoryStore();
  await saveQueue({ ...emptyQueue(88), events: [stop("w")] }, store);
  const order: string[] = [];
  const { api } = scriptedApi({ 88: [new TypeError("Failed to fetch")] }, order);
  const done = startEngineReconciliation("init", { store, api, delaysMs: [60_000] });
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.deepEqual(order, ["events:88:fail"]);  // ждёт паузу, не крутится
  wakeEngineReconciliation();  // `online` / приложение снова на экране
  await done;
  assert.deepEqual(order, ["events:88:fail", "events:88:ok"]);
});

test("F1: одна сверка на приложение — повторный старт будит идущую и возвращает её же", async () => {
  const store = memoryStore();
  await saveQueue({ ...emptyQueue(89), events: [stop("s")] }, store);
  const order: string[] = [];
  const { api } = scriptedApi({ 89: [new TypeError("Failed to fetch")] }, order);
  const done = startEngineReconciliation("init", { store, api, delaysMs: [60_000] });
  await new Promise((resolve) => setTimeout(resolve, 5));
  assert.equal(startEngineReconciliation("init", { store, api }), done);  // online → тот же promise, повтор сейчас
  await done;
  assert.deepEqual(order, ["events:89:fail", "events:89:ok"]);
});

// --- #306: запрос сверки посреди идущего прохода (экран освободил очередь) -------------------------

/** Сервер на настоящем движке (liveEngine.ts — зеркало серверного, общие векторы): POST событий —
 * зажатый client_at, применение, проекция до «сейчас»; чтение с проекцией (GET /active, список сессий) —
 * project(now). Дубль client_event_id — no-op. */
function engineServer(sessions: Record<number, { plan: EnginePlan; startAt: number }>) {
  const state = new Map<number, EngineState>();
  const seen = new Set<string>();
  for (const [id, { plan, startAt }] of Object.entries(sessions)) {
    state.set(Number(id), start(plan, startAt)[0]);
  }
  const server = {
    now: 0,
    plan: (id: number) => sessions[id].plan,
    state: (id: number) => state.get(id) as EngineState,
    post(id: number, events: { client_event_id: string; type: string; payload: Record<string, unknown>; client_at?: string | null }[]) {
      const plan = sessions[id].plan;
      let current = state.get(id) as EngineState;
      const results = events.map((event) => {
        if (seen.has(event.client_event_id)) {
          return { client_event_id: event.client_event_id, outcome: "duplicate" };
        }
        seen.add(event.client_event_id);
        const clientAt = event.client_at ? Date.parse(event.client_at) : null;
        const at = clampClientAt(clientAt, current.last_at, server.now);
        const before = JSON.stringify(current);
        [current] = applyEvent(plan, current, { type: event.type, payload: event.payload } as EngineEvent, at);
        return { client_event_id: event.client_event_id, outcome: JSON.stringify(current) === before ? "noop" : "applied" };
      });
      [current] = project(plan, current, server.now);
      state.set(id, current);
      return { engine_status: current.status, event_results: results };
    },
    /** GET /sessions/live/active или список сессий: сервер проецирует истёкшие дедлайны. */
    projectingRead(id: number) {
      state.set(id, project(sessions[id].plan, state.get(id) as EngineState, server.now)[0]);
    },
  };
  return server;
}

function deferred<T = void>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

const TIMED_15: EnginePlan = {
  blocks: [
    { kind: "sets", prep_seconds: 0, rest_after_block_seconds: 5, extra_sets_allowed: true,
      sets: [{ kind: "time", target: 15, rest_after_seconds: null }] },
    { kind: "sets", prep_seconds: 0, rest_after_block_seconds: null, extra_sets_allowed: true,
      sets: [{ kind: "reps", target: 3, rest_after_seconds: null }] },
  ],
};
const INTERVAL: EnginePlan = {
  blocks: [{ kind: "interval", prep_seconds: 3, rest_after_block_seconds: null, extra_sets_allowed: false,
    interval: { work_seconds: 5, rest_seconds: 4, rounds: 2, record_reps_per_round: false } }],
};

/**
 * Гонка ревьюера: сверка App идёт (очередь сессии A, её POST в полёте); очередь сессии S принадлежит
 * открытому экрану (claim) — проход её пропускает. Посреди POST сессии A экран закрывается: releaseQueue(S) +
 * startEngineReconciliation() (так делает очистка LiveEngineScreen). Затем открыт Журнал (чтение с проекцией).
 */
async function claimReleaseRace(opts: { sQueue: QueuedEngineEventLike[]; serverS: { plan: EnginePlan; startAt: number }; readAtMs: number }) {
  const A = 901;
  const S = 902;
  const server = engineServer({ [A]: { plan: TIMED_15, startAt: 0 }, [S]: opts.serverS });
  const store = memoryStore();
  // S сохранена раньше A: проход ПРОХОДИТ мимо S (она ещё за экраном) и только потом шлёт A — ровно гонка ревьюера.
  await saveQueue({ ...emptyQueue(S), events: opts.sQueue }, store);
  await saveQueue({ ...emptyQueue(A), events: [{ client_event_id: "a-stop", type: "stop", payload: { phase_seq: server.state(A).phase_seq }, client_at_ms: 2_000 }] }, store);
  const order: string[] = [];
  const aInFlight = deferred();
  const aRelease = deferred();
  let passes = 0;
  const countingStore: QueueStore = { ...store, keys: async () => { passes += 1; return store.keys(); } };
  const api: DrainApi = {
    postEvents: (async (_init: string, id: number, events: Parameters<typeof server.post>[1]) => {
      order.push(`events:${id}`);
      if (id === A) {
        aInFlight.resolve();
        await aRelease.promise;  // POST сессии A ещё в полёте
      }
      return server.post(id, events);
    }) as unknown as DrainApi["postEvents"],
    complete: (async () => ({ status: "completed" })) as unknown as DrainApi["complete"],
  };
  server.now = opts.readAtMs;  // приложение открыто через много секунд после дедлайнов
  claimQueue(S);
  const reconcile = startEngineReconciliation("init", { store: countingStore, api, delaysMs: [5] });
  await aInFlight.promise;  // первый проход: S уже пропущена (claim), A в полёте
  releaseQueue(S);  // экран закрыт…
  const joined = startEngineReconciliation("init", { store: countingStore, api, delaysMs: [5] });  // …и просит сверку
  const journal = (async () => {
    await awaitEngineReconciliation();  // fetchSessions / fetchActiveLiveSession (apiV2.ts)
    order.push("journal");
    server.projectingRead(S);
  })();
  aRelease.resolve();
  await Promise.all([reconcile, journal]);
  return { server, store, order, passes, joined, reconcile, S };
}

type QueuedEngineEventLike = { client_event_id: string; type: string; payload: Record<string, unknown>; client_at_ms: number };

test("гонка ревьюера: очередь, освобождённая экраном посреди прохода, сверяется до открытия ворот", async () => {
  const stopS = { client_event_id: "s-stop", type: "stop", payload: { phase_seq: start(TIMED_15, 0)[0].phase_seq }, client_at_ms: 4_000 };
  const { server, store, order, passes, joined, reconcile, S } = await claimReleaseRace({
    sQueue: [stopS], serverS: { plan: TIMED_15, startAt: 0 }, readAtMs: 100_000,
  });
  assert.equal(server.state(S).logs[0].value, 4);  // «Стоп» на 4 с — не цель 15
  assert.equal(joined, reconcile);  // single-flight: тот же promise, второй петли нет
  assert.deepEqual(order, ["events:901", "events:902", "journal"]);  // S досылается (второй проход) ДО чтения с проекцией
  assert.equal(passes, 2);  // второй полный проход — ровно один
  assert.equal(store.data.size, 0);
});

test("гонка ревьюера, пауза: пауза доходит раньше проекции — активна, на паузе, остаток верный", async () => {
  const [initial] = start(INTERVAL, 0);
  const atWork = project(INTERVAL, initial, 3_500)[0];  // раунд 1 идёт с 3 с, дедлайн — 8 с
  const pauseS = { client_event_id: "s-pause", type: "pause", payload: { phase_seq: atWork.phase_seq }, client_at_ms: 4_000 };
  const { server, order, S } = await claimReleaseRace({
    sQueue: [pauseS], serverS: { plan: INTERVAL, startAt: 0 }, readAtMs: 600_000,
  });
  const state = server.state(S);
  assert.equal(state.status, "active");  // не завершилась сама
  assert.equal(state.paused_at, 4_000);
  assert.equal(state.paused_remaining_ms, 4_000);
  assert.equal(remainingMs(state, 600_000), 4_000);
  assert.deepEqual(order, ["events:901", "events:902", "journal"]);
});

test("несколько запросов посреди одного прохода: одна петля, один дополнительный проход, ворота — после", async () => {
  const store = memoryStore();
  await saveQueue({ ...emptyQueue(912), events: [stop("m-s")] }, store);  // пропускается первым проходом (claim)
  await saveQueue({ ...emptyQueue(911), events: [stop("m-a")] }, store);
  let passes = 0;
  const countingStore: QueueStore = { ...store, keys: async () => { passes += 1; return store.keys(); } };
  const inFlight = deferred();
  const releaseA = deferred();
  const order: string[] = [];
  const { api } = fakeApi({
    events: (sessionId, ids) => {
      order.push(`events:${sessionId}`);
      return { engine_status: "active", event_results: ids.map((id) => ({ client_event_id: id, outcome: "applied" })) };
    },
  });
  const slowApi: DrainApi = {
    ...api,
    postEvents: (async (...args: Parameters<DrainApi["postEvents"]>) => {
      if (args[1] === 911) {
        inFlight.resolve();
        await releaseA.promise;
      }
      return api.postEvents(...args);
    }) as DrainApi["postEvents"],
  };
  claimQueue(912);
  const run = startEngineReconciliation("init", { store: countingStore, api: slowApi });
  await inFlight.promise;
  releaseQueue(912);
  const joins = [1, 2, 3, 4, 5].map(() => startEngineReconciliation("init", { store: countingStore, api: slowApi }));
  for (const joined of joins) {
    assert.equal(joined, run);  // параллельных петель нет
  }
  const read = gatedRead(order, "read");
  releaseA.resolve();
  await Promise.all([run, read]);
  assert.equal(passes, 2);  // пять запросов — один дополнительный полный проход, не пять
  assert.deepEqual(order, ["events:911", "events:912", "read"]);
});

test("запрос посреди прохода без изменений очередей: не больше одного стабилизирующего прохода, ворота открываются", async () => {
  const store = memoryStore();
  await saveQueue({ ...emptyQueue(921), events: [stop("n-a")] }, store);
  let passes = 0;
  const countingStore: QueueStore = { ...store, keys: async () => { passes += 1; return store.keys(); } };
  const inFlight = deferred();
  const release = deferred();
  const { api } = fakeApi();
  const slowApi: DrainApi = {
    ...api,
    postEvents: (async (...args: Parameters<DrainApi["postEvents"]>) => {
      inFlight.resolve();
      await release.promise;
      return api.postEvents(...args);
    }) as DrainApi["postEvents"],
  };
  const run = startEngineReconciliation("init", { store: countingStore, api: slowApi });
  await inFlight.promise;
  assert.equal(startEngineReconciliation("init", { store: countingStore, api: slowApi }), run);
  release.resolve();
  await run;
  assert.equal(passes, 2);
  const order: string[] = [];
  await gatedRead(order, "read");
  assert.deepEqual(order, ["read"]);
});

test("запрос сразу после завершения сверки начинает новую (не теряется в окне выхода)", async () => {
  const store = memoryStore();
  const { api, calls } = fakeApi();
  const first = startEngineReconciliation("init", { store, api });
  await first;
  await saveQueue({ ...emptyQueue(931), events: [stop("late")] }, store);  // экран закрылся с очередью
  const second = startEngineReconciliation("init", { store, api });
  assert.notEqual(second, first);
  await second;
  assert.deepEqual(calls, [{ kind: "events", sessionId: 931, ids: ["late"] }]);
});

test("гонка ревьюера через настоящие apiV2.fetchSessions / fetchActiveLiveSession: запрос уходит в сеть только после S", async () => {
  const S = 942;
  const A = 941;
  const store = memoryStore();
  await saveQueue({ ...emptyQueue(S), events: [stop("g-s", 4_000)] }, store);
  await saveQueue({ ...emptyQueue(A), events: [stop("g-a")] }, store);
  const order: string[] = [];
  const aInFlight = deferred();
  const aRelease = deferred();
  const { api } = fakeApi();
  const slowApi: DrainApi = {
    ...api,
    postEvents: (async (...args: Parameters<DrainApi["postEvents"]>) => {
      order.push(`events:${args[1]}`);  // запрос ушёл
      if (args[1] === A) {
        aInFlight.resolve();
        await aRelease.promise;
      }
      return api.postEvents(...args);
    }) as DrainApi["postEvents"],
  };
  const realFetch = globalThis.fetch;
  globalThis.fetch = (async (input: string | URL | Request) => {
    const url = String(input);
    order.push(url.includes("/live/active") ? "GET active" : "GET sessions");
    const body = url.includes("/live/active") ? { session: null } : { sessions: [] };
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
  try {
    claimQueue(S);
    const run = startEngineReconciliation("init", { store, api: slowApi });
    await aInFlight.promise;  // S уже пропущена, POST сессии A в полёте
    releaseQueue(S);
    void startEngineReconciliation("init", { store, api: slowApi });
    const reads = Promise.all([fetchSessions("init"), fetchActiveLiveSession("init")]);  // Журнал + App
    await new Promise((resolve) => setTimeout(resolve, 5));
    assert.deepEqual(order, ["events:941"]);  // ни одного чтения с проекцией, пока S не дослана
    aRelease.resolve();
    await Promise.all([run, reads]);
    assert.deepEqual(order.slice(0, 2), ["events:941", "events:942"]);
    assert.deepEqual(order.slice(2).sort(), ["GET active", "GET sessions"]);
  } finally {
    globalThis.fetch = realFetch;
  }
});

/**
 * N1 (финальное ревью #306): окно выхода сверки. Проход решил «стабильно» — и в тот же синхронный шаг
 * снимает single-flight (`reconciling = null`). Раньше снятие было в `.finally` — на несколько микрозадач
 * позже: запрос, пришедший в этом окне, присоединялся к уже завершившейся сверке, его rerun никто не читал,
 * ворота открывались, и чтение с проекцией обгоняло очередь S.
 *
 * Окно — конкретное смещение в микрозадачах после ответа на POST сессии A; зависит от числа await внутри
 * drainEngineQueues, поэтому тест перебирает небольшой диапазон смещений (детерминированно, без таймеров):
 * на каждом смещении экран S закрывается (releaseQueue + startEngineReconciliation) и сразу открывается Журнал
 * (настоящий fetchSessions). На любом смещении «Стоп» S на 4 с должен дойти раньше проекции.
 */
test("N1: запрос в окне выхода сверки не теряется — «Стоп» S доходит раньше проекции на любом смещении микрозадач", async () => {
  const lostAt: number[] = [];
  for (let offset = 0; offset <= 20; offset += 1) {
    const S = 960 + offset * 2;
    const A = S + 1;
    const server = engineServer({ [S]: { plan: TIMED_15, startAt: 0 }, [A]: { plan: TIMED_15, startAt: 0 } });
    server.now = 100_000;  // приложение открыто давно после дедлайнов: проекция записала бы цель 15 с
    const store = memoryStore();
    const phaseSeq = server.state(S).phase_seq;
    await saveQueue({ ...emptyQueue(S), events: [{ client_event_id: `n1-s-${offset}`, type: "stop", payload: { phase_seq: phaseSeq }, client_at_ms: 4_000 }] }, store);
    await saveQueue({ ...emptyQueue(A), events: [{ client_event_id: `n1-a-${offset}`, type: "stop", payload: { phase_seq: phaseSeq }, client_at_ms: 2_000 }] }, store);
    const order: string[] = [];
    let screenClosed: Promise<unknown> = Promise.resolve();
    const api: DrainApi = {
      postEvents: ((_init: string, id: number, events: Parameters<typeof server.post>[1]) => {
        order.push(`events:${id}`);
        const response = Promise.resolve(server.post(id, events));
        if (id === A) {
          // Экран S закрывается через `offset` микрозадач после ответа сервера на POST сессии A.
          screenClosed = response.then(async () => {
            for (let i = 0; i < offset; i += 1) {
              await Promise.resolve();
            }
            releaseQueue(S);
            void startEngineReconciliation("init", { store, api });
            const realFetch = globalThis.fetch;
            globalThis.fetch = (async () => {
              order.push("GET /sessions");
              server.projectingRead(S);  // сервер проецирует дедлайны идущих сессий
              return new Response(JSON.stringify({ sessions: [] }), { status: 200, headers: { "Content-Type": "application/json" } });
            }) as typeof fetch;
            try {
              await fetchSessions("init");  // Журнал — за воротами (apiV2.ts)
            } finally {
              globalThis.fetch = realFetch;
            }
          });
        }
        return response;
      }) as unknown as DrainApi["postEvents"],
      complete: (async () => ({ status: "completed" })) as unknown as DrainApi["complete"],
    };
    claimQueue(S);  // S за открытым экраном: первый проход её пропускает
    await startEngineReconciliation("init", { store, api });
    await screenClosed;
    await awaitEngineReconciliation();
    const stored = server.state(S).logs[0]?.value;
    const sentBeforeRead = order.indexOf(`events:${S}`) >= 0 && order.indexOf(`events:${S}`) < order.indexOf("GET /sessions");
    if (stored !== 4 || !sentBeforeRead || store.data.size !== 0) {
      lostAt.push(offset);
    }
    assert.equal(stored, 4, `смещение ${offset}: «Стоп» S записан как ${stored} (цель 15 = очередь обогнана проекцией); ${JSON.stringify(order)}`);
    assert.ok(sentBeforeRead, `смещение ${offset}: ${JSON.stringify(order)}`);
  }
  assert.deepEqual(lostAt, []);
});

// --- Открытый экран: повтор досылки после временного сбоя при браузере «онлайн» ----------------------------

function fakeTimers() {
  const pending = new Map<number, { run: () => void; ms: number }>();
  let next = 0;
  return {
    pending,
    timers: {
      set: (run: () => void, ms: number) => {
        pending.set(++next, { run, ms });
        return next;
      },
      clear: (handle: unknown) => void pending.delete(handle as number),
    },
    fire() {
      const [[handle, entry]] = [...pending.entries()];
      pending.delete(handle);
      entry.run();
    },
  };
}

test("экран: временный сбой — повтор сам с растущей паузой 1, 2, 4, 8, 15, 15 с; не больше одного ожидающего", () => {
  const clock = fakeTimers();
  let runs = 0;
  const retry = createSyncRetry(() => { runs += 1; }, undefined, clock.timers);
  const delays: number[] = [];
  for (let i = 0; i < 6; i += 1) {
    retry.schedule();
    retry.schedule();  // второй сбой до повтора не ставит второй таймер (нет дублирующих запросов)
    assert.equal(clock.pending.size, 1);
    delays.push([...clock.pending.values()][0].ms);
    clock.fire();
  }
  assert.deepEqual(delays, [1_000, 2_000, 4_000, 8_000, 15_000, 15_000]);
  assert.equal(runs, 6);
});

test("экран: удачная досылка сбрасывает паузу; досылка по действию/online снимает ожидающий повтор; закрытие — тоже", () => {
  const clock = fakeTimers();
  let runs = 0;
  const retry = createSyncRetry(() => { runs += 1; }, undefined, clock.timers);
  retry.schedule();
  clock.fire();
  retry.schedule();
  assert.equal([...clock.pending.values()][0].ms, 2_000);
  retry.reset();
  assert.equal(clock.pending.size, 0);
  retry.schedule();
  assert.equal([...clock.pending.values()][0].ms, 1_000);
  retry.cancel();
  assert.equal(clock.pending.size, 0);
  assert.equal(runs, 1);
});

// --- Аудит #322: досылки экрана привязаны к его монтированию -------------------------------------------------

test("экран: досылка, ушедшая до ухода/unmount, по возвращении устарела — ни повтора, ни новой досылки", () => {
  const life = createScreenLifecycle();
  assert.equal(life.token(), null);  // до монтирования досылку не начинать
  life.mount();
  const inFlight = life.token() as number;
  assert.equal(life.isCurrent(inFlight), true);
  life.unmount();  // «Выйти»/Back: очистка эффекта
  assert.equal(life.isCurrent(inFlight), false);  // поздний 503/ответ — устарел
  assert.equal(life.token(), null);  // и новую досылку (таймер, resync) не начать
});

test("экран: StrictMode/повторный mount и смена сессии — старое поколение не оживает, новое работает", () => {
  const life = createScreenLifecycle();
  life.mount();
  const first = life.token() as number;
  life.unmount();
  life.mount();  // StrictMode (mount → cleanup → mount) или эффект новой сессии
  const second = life.token() as number;
  assert.notEqual(first, second);
  assert.equal(life.isCurrent(first), false);
  assert.equal(life.isCurrent(second), true);
  life.unmount();
  life.mount();
  assert.equal(life.isCurrent(second), false);
});

test("экран: поздний сбой ушедшей досылки не ставит повтор — серию шлёт только сверка App", () => {
  // Та же связка, что у LiveEngineScreen: catch планирует повтор только для текущего поколения.
  const clock = fakeTimers();
  const life = createScreenLifecycle();
  let sends = 0;
  const retry = createSyncRetry(() => { sends += 1; }, undefined, clock.timers);
  const onTransientFailure = (token: number) => {
    if (life.isCurrent(token)) {
      retry.schedule();
    }
  };
  life.mount();
  const token = life.token() as number;
  life.unmount();
  retry.cancel();  // очистка — до позднего ответа
  onTransientFailure(token);  // 503 пришёл через 2,5 с после ухода
  assert.equal(clock.pending.size, 0);
  assert.equal(sends, 0);
});
