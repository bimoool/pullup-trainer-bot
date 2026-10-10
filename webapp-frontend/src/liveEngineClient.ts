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

import { del, get, set } from "idb-keyval";

import { applyEvent, project, type EngineEvent, type EnginePlan, type EngineState, type Payload } from "./liveEngine.ts";

const STORE_KEY = "pullup:v2:live-engine-queue";

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

export async function loadQueue(sessionId: number): Promise<EngineQueue> {
  try {
    const stored = await get<EngineQueue>(STORE_KEY);
    return stored && stored.sessionId === sessionId ? stored : emptyQueue(sessionId);
  } catch {
    return emptyQueue(sessionId);
  }
}

export async function saveQueue(queue: EngineQueue): Promise<void> {
  await set(STORE_KEY, queue);
}

export async function clearQueue(): Promise<void> {
  await del(STORE_KEY);
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
