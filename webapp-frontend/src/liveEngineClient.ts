/**
 * Клиентская сторона Live Engine v2 (issue #306, LIVE_ENGINE_V2 §2): очередь событий в IndexedDB,
 * серверное смещение часов и отображаемая проекция.
 *
 * Авторитет переходов — сервер. Клиент только:
 *  - хранит НЕотправленные события (офлайн/в полёте) с client_event_id и client_at (C4);
 *  - рисует `project(fold(server.state, queue), now + offset)` той же функцией переходов, что сервер
 *    (liveEngine.ts — зеркало, общие векторы) — фон/офлайн/между ответами;
 *  - любой ответ сервера ЦЕЛИКОМ заменяет базовое состояние; из очереди уходит отправленное.
 * Своих констант длительности, второго таймера и override-ов дедлайна здесь нет (C2).
 */

import { del, get, keys, set } from "idb-keyval";

import { completeLiveSession, postLiveEngineEvents } from "./apiV2.ts";
import { holdEngineReconciliation } from "./engineGate.ts";
import { applyEvent, project, type EngineEvent, type EnginePlan, type EngineState, type Payload } from "./liveEngine.ts";

/** Очередь — своя у каждой сессии (`…:<session_id>`): старт сессии B не стирает недосланное сессии A. */
const STORE_PREFIX = "pullup:v2:live-engine-queue:";
/** Ключ до #306 B1 (одна очередь на всё приложение) — читается один раз и переезжает под ключ сессии. */
const LEGACY_STORE_KEY = "pullup:v2:live-engine-queue";

function storeKey(sessionId: number): string {
  return `${STORE_PREFIX}${sessionId}`;
}

export interface QueuedEngineEvent {
  client_event_id: string;
  type: string;
  payload: Payload;
  /** Серверное время события (Date.now() + offset) в мс. */
  client_at_ms: number;
}

export interface EngineQueue {
  sessionId: number;
  events: QueuedEngineEvent[];
  /** Оценка/заметка, поставленные «Сохранить и завершить» (уходят POST …/complete после событий). */
  complete: { effort: string | null; comment: string | null } | null;
}

export function emptyQueue(sessionId: number): EngineQueue {
  return { sessionId, events: [], complete: null };
}

/** Хранилище очередей (IndexedDB; в тестах — подмена). */
export interface QueueStore {
  get(key: string): Promise<EngineQueue | undefined>;
  set(key: string, value: EngineQueue): Promise<void>;
  del(key: string): Promise<void>;
  keys(): Promise<string[]>;
}

const idbStore: QueueStore = {
  get: (key) => get<EngineQueue>(key),
  set: (key, value) => set(key, value),
  del: (key) => del(key),
  keys: async () => (await keys()).filter((key): key is string => typeof key === "string"),
};

export async function loadQueue(sessionId: number, store: QueueStore = idbStore): Promise<EngineQueue> {
  try {
    await migrateLegacyQueue(store);
    const stored = await store.get(storeKey(sessionId));
    return stored && stored.sessionId === sessionId ? stored : emptyQueue(sessionId);
  } catch {
    return emptyQueue(sessionId);
  }
}

export async function saveQueue(queue: EngineQueue, store: QueueStore = idbStore): Promise<void> {
  await store.set(storeKey(queue.sessionId), queue);
}

export async function clearQueue(sessionId: number, store: QueueStore = idbStore): Promise<void> {
  await store.del(storeKey(sessionId));
}

/** Все сохранённые очереди (по сессиям), включая переехавшую очередь старого формата. */
export async function loadAllQueues(store: QueueStore = idbStore): Promise<EngineQueue[]> {
  await migrateLegacyQueue(store);
  const queues: EngineQueue[] = [];
  for (const key of await store.keys()) {
    if (!key.startsWith(STORE_PREFIX)) {
      continue;
    }
    const stored = await store.get(key);
    if (stored && typeof stored.sessionId === "number") {
      queues.push(stored);
    }
  }
  return queues;
}

async function migrateLegacyQueue(store: QueueStore): Promise<void> {
  const legacy = await store.get(LEGACY_STORE_KEY);
  if (legacy === undefined) {
    return;
  }
  if (typeof legacy.sessionId === "number" && (await store.get(storeKey(legacy.sessionId))) === undefined) {
    await store.set(storeKey(legacy.sessionId), legacy);
  }
  await store.del(LEGACY_STORE_KEY);
}

function hasWork(queue: EngineQueue): boolean {
  return queue.events.length > 0 || queue.complete !== null;
}

/** Смещение серверных часов: server_time_ms против середины запроса по часам клиента (C1). */
export function serverOffsetMs(serverTimeMs: number, requestStartedMs: number, responseReceivedMs: number): number {
  return Math.round(serverTimeMs - (requestStartedMs + responseReceivedMs) / 2);
}

/** Отображаемое состояние: подтверждённое сервером + ещё не подтверждённые события (в порядке
 * возникновения, каждое со своим временем) + дедлайны до «сейчас». Тот же шаг, что сервер (applyEvent). */
export function displayState(
  plan: EnginePlan, serverState: EngineState, queue: QueuedEngineEvent[], nowServerMs: number,
): EngineState {
  let state = serverState;
  for (const event of queue) {
    const at = Math.max(state.last_at, Math.min(event.client_at_ms, nowServerMs));
    [state] = applyEvent(plan, state, { type: event.type, payload: event.payload } as EngineEvent, at);
  }
  [state] = project(plan, state, nowServerMs);
  return state;
}

/** Ответ сервера пришёл: из очереди уходят события, которые он уже учёл (applied/noop/duplicate). */
export function dropAcknowledged(queue: EngineQueue, acknowledged: string[]): EngineQueue {
  const done = new Set(acknowledged);
  return { ...queue, events: queue.events.filter((event) => !done.has(event.client_event_id)) };
}

export function newEvent(type: string, payload: Payload, nowServerMs: number): QueuedEngineEvent {
  return { client_event_id: crypto.randomUUID(), type, payload, client_at_ms: nowServerMs };
}

/** API досылки (в тестах — подмена). */
export interface DrainApi {
  postEvents: typeof postLiveEngineEvents;
  complete: typeof completeLiveSession;
}

const httpApi: DrainApi = { postEvents: postLiveEngineEvents, complete: completeLiveSession };

export interface DrainResult {
  /** Осталось недосланное из-за сети/временной ошибки — сервер ещё не знает часть событий пользователя. */
  pending: boolean;
}

function httpStatus(error: unknown): number | null {
  const raw = (error as { status?: unknown } | null)?.status;
  return typeof raw === "number" && Number.isFinite(raw) ? raw : null;
}

/** 404 — сессии нет/чужая, 409 — сессия не движка v2: досылать некуда, очередь снимается. */
function isGone(error: unknown): boolean {
  const status = httpStatus(error);
  return status === 404 || status === 409;
}

function isTransient(error: unknown): boolean {
  const status = httpStatus(error);
  return status === null || status >= 500 || status === 408 || status === 429;
}

/**
 * #306 B1 — досылка сохранённых очередей движка v2 БЕЗ экрана тренировки (App: при запуске до любого
 * запроса, способного спроецировать дедлайны — GET /sessions/live/active, список сессий; и по `online`).
 *
 * Офлайн-действие пользователя (Стоп в 20 с из 60, пауза) случилось ДО дедлайна, поэтому должно дойти до
 * сервера раньше, чем ленивая проекция запишет этот дедлайн: иначе событие станет устаревшим no-op, а
 * подход на время запишется целью. Сервер остаётся авторитетом — он зажимает client_at, упорядочивает и
 * дедуплицирует (client_event_id) события; клиент только отправляет их первым делом.
 *
 * Та же очередь несёт оценку/заметку «Сохранить»: сессия, завершённая сервером сама, в GET /active уже не
 * видна, экран для неё не откроется — оценка уходит отсюда (идемпотентный complete дописывает её).
 *
 * Повтор после потерянного ответа шлёт те же client_event_id — сервер отвечает duplicate (200, no-op).
 */
export async function drainEngineQueues(
  initDataRaw: string, store: QueueStore = idbStore, api: DrainApi = httpApi,
  skip: ReadonlySet<number> = claimedSessions,
): Promise<DrainResult> {
  let queues: EngineQueue[];
  try {
    queues = await loadAllQueues(store);
  } catch {
    return { pending: false };  // хранилище недоступно — досылать нечего
  }
  let pending = false;
  for (const stored of queues) {
    if (skip.has(stored.sessionId)) {
      continue;  // очередью владеет открытый экран этой сессии — он сам её досылает
    }
    let queue = stored;
    try {
      if (!hasWork(queue)) {
        await store.del(storeKey(queue.sessionId));
        continue;
      }
      if (queue.events.length > 0) {
        const response = await api.postEvents(initDataRaw, queue.sessionId, queue.events.map((event) => ({
          client_event_id: event.client_event_id, type: event.type, payload: event.payload,
          client_at: new Date(event.client_at_ms).toISOString(),
        })));
        queue = dropAcknowledged(queue, response.event_results.map((r) => r.client_event_id));
        if (response.engine_status === "cancelled") {
          await store.del(storeKey(queue.sessionId));
          continue;
        }
        await saveQueue(queue, store);
      }
      if (queue.events.length === 0 && queue.complete !== null) {
        await api.complete(initDataRaw, queue.sessionId, false, queue.complete);
        queue = { ...queue, complete: null };
      }
      if (hasWork(queue)) {
        await saveQueue(queue, store);
      } else {
        await store.del(storeKey(queue.sessionId));
      }
    } catch (error) {
      if (isGone(error)) {
        await store.del(storeKey(queue.sessionId)).catch(() => undefined);
      } else if (isTransient(error)) {
        pending = true;  // очередь цела; следующая досылка — по `online` или при открытии экрана
      }
      // иной отказ (4xx) — очередь не трогаем (экран тренировки покажет причину), но и не ждём её
    }
  }
  return { pending };
}

// --- #306 F1: сверка с повторами и ворота для чтений с проекцией ------------------------------------

/** Сессии, чьей очередью сейчас владеет открытый LiveEngineScreen: сверка App их не трогает (иначе две
 * записи одной очереди в IndexedDB затёрли бы друг друга). */
const claimedSessions = new Set<number>();

export function claimQueue(sessionId: number): void {
  claimedSessions.add(sessionId);
}

export function releaseQueue(sessionId: number): void {
  claimedSessions.delete(sessionId);
}

/** Паузы между повторами при временном сбое (сеть/5xx): ограниченный рост, без busy-loop. */
export const RECONCILE_RETRY_DELAYS_MS = [1_000, 2_000, 4_000, 8_000, 15_000];

export interface ReconcileOptions {
  store?: QueueStore;
  api?: DrainApi;
  delaysMs?: readonly number[];
}

let reconciling: Promise<void> | null = null;
let wakeReconcile: (() => void) | null = null;

/**
 * #306 F1 — сверка всех сохранённых очередей движка v2, пока она не удастся.
 *
 * Пока сверка идёт, чтения, которые сервер сопровождает проекцией дедлайнов (GET /sessions/live/active,
 * список сессий), ждут её (engineGate.ts → apiV2.ts): сохранённое действие пользователя, сделанное до
 * дедлайна, всегда доходит раньше этого дедлайна. Временный сбой (сеть, 5xx, 408/429) — очередь цела,
 * повтор через 1, 2, 4, 8, 15, 15… с; ворота держатся. Окончательный ответ (404/409, прочий 4xx) повтор не
 * вызывает. Одна сверка на приложение: повторный вызов будит ждущую паузу и возвращает тот же promise;
 * `wakeEngineReconciliation` — то же по `online`/возврату на экран. Нет очередей — завершается сразу (одно
 * чтение IndexedDB, без сети).
 */
export function startEngineReconciliation(initDataRaw: string, options: ReconcileOptions = {}): Promise<void> {
  if (reconciling !== null) {
    wakeEngineReconciliation();
    return reconciling;
  }
  const delays = options.delaysMs ?? RECONCILE_RETRY_DELAYS_MS;
  const run = (async () => {
    for (let attempt = 0; ; attempt += 1) {
      const { pending } = await drainEngineQueues(initDataRaw, options.store, options.api);
      if (!pending) {
        return;
      }
      await new Promise<void>((resolve) => {
        const timer = setTimeout(done, delays[Math.min(attempt, delays.length - 1)]);
        function done() {
          clearTimeout(timer);
          wakeReconcile = null;
          resolve();
        }
        wakeReconcile = done;
      });
    }
  })().finally(() => {
    reconciling = null;
  });
  reconciling = run;
  holdEngineReconciliation(run);
  return run;
}

/** Повторить сверку сейчас (вернулась сеть, приложение снова на экране), не дожидаясь паузы. */
export function wakeEngineReconciliation(): void {
  wakeReconcile?.();
}
