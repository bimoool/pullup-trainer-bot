import type { LiveSessionCompleteResponse } from "./apiV2.ts";

/**
 * Завершение живой тренировки, поставленное в очередь (#287, HIGH 1/2): чистая машина состояний
 * статуса «завершение в очереди» Live-экрана. Без DOM/React — проверяется юнит-тестами
 * (tests/liveFinish.test.ts).
 *
 * Завершение сначала фиксируется локально (`completeRequested` в IndexedDB), затем досылается
 * single-flight флашем. Пока оно не принято сервером, управление тренировкой скрыто, а экран
 * показывает один из статусов ниже. Ни в одном статусе нет тупика: офлайн — ждём сеть (и флаш по
 * событию `online`), онлайн без запроса в полёте — всегда видна кнопка повтора, Back/«Выйти»
 * уводят с экрана (данные остаются в IndexedDB и досылаются при следующем открытии).
 */

/** Ошибка досылки: transient — сеть/5xx (повтор поможет), rejected — сервер отверг (4xx),
 * auth — initData просрочен (401: помогает только повторное открытие Mini App). */
export type SyncFailureKind = "transient" | "rejected" | "auth";

export interface SyncFailure {
  kind: SyncFailureKind;
  message: string;
  /** HTTP-статус, если ответ был; null — сетевой сбой (fetch не дошёл). */
  status: number | null;
}

export function classifySyncError(error: unknown): SyncFailure {
  const message = error instanceof Error ? error.message : String(error);
  const raw = (error as { status?: unknown } | null)?.status;
  const status = typeof raw === "number" && Number.isFinite(raw) ? raw : null;
  if (status === 401) {
    return { kind: "auth", message, status };
  }
  // 408/429 — «попробуй позже», не отказ по существу.
  if (status !== null && status >= 400 && status < 500 && status !== 408 && status !== 429) {
    return { kind: "rejected", message, status };
  }
  return { kind: "transient", message, status };
}

/**
 * - none — завершение не запрошено;
 * - offline — сети нет: результат на устройстве, уйдёт по событию `online`;
 * - sending — флаш в полёте;
 * - retry — онлайн, запроса в полёте нет, завершение не принято (временная ошибка или ещё не
 *   отправлялось) — видна «Отправить ещё раз»;
 * - rejected — сервер отверг завершение (4xx/401): локальные данные не трогаем, объясняем,
 *   повтор остаётся доступен.
 */
export type FinishStatus = "none" | "offline" | "sending" | "retry" | "rejected";

export function finishStatus(state: {
  finishing: boolean;
  online: boolean;
  syncing: boolean;
  failure: SyncFailure | null;
}): FinishStatus {
  if (!state.finishing) {
    return "none";
  }
  if (!state.online) {
    return "offline";
  }
  if (state.syncing) {
    return "sending";
  }
  if (state.failure !== null && state.failure.kind !== "transient") {
    return "rejected";
  }
  return "retry";
}

/**
 * Флаш завершения получил 404 («Live session not found»: сервер отдаёт его и на переход фазы уже
 * не идущей сессии). Если сессия больше не активна на сервере (GET /sessions/live/active вернул
 * не её), значит она уже завершена — например, прошлый `complete` дошёл, а ответ потерялся, — и
 * повторный идемпотентный `complete` вернёт её итог. Если же она всё ещё активна — это настоящий
 * отказ, локальные данные не трогаем.
 */
export function isFinishedElsewhere(failure: SyncFailure, activeSessionId: number | null, ownSessionId: number): boolean {
  return failure.status === 404 && activeSessionId !== ownSessionId;
}

/** «Начать» следующего блока недоступно, пока завершение в очереди: старт блока сбросил бы
 * локальный снимок вместе с `completeRequested` и оценкой тренировки. */
export function canStartNextBlock(local: { completeRequested: unknown } | null): boolean {
  return local !== null && local.completeRequested === null;
}

/** Ответ несёт итог канонического завершения (#307): прогрессию (старую или V5.6) или причину её пропуска.
 * Ответ событий уже завершённой сессии без нового завершения — нет (все три поля пусты). */
export function carriesCompletionOutcome(response: LiveSessionCompleteResponse): boolean {
  return response.status === "completed" && (
    response.progression_result != null || response.course_progression != null || response.progression_skipped_reason != null
  );
}

/**
 * Итог для Summary движка v2. Тренировку завершает событие (последний подход, `confirm_blocks`, `finish_early`) —
 * его ответ несёт фактический итог первого завершения; «Сохранить» затем шлёт оценку идемпотентным
 * POST …/complete, а тот честно отвечает `already_completed` без прогрессии (повторно её не считает). Показывать
 * этот второй ответ как итог — потерянная прибавка V5.6/«досрочно» (виден только нейтральный «Тренировка сохранена»). Поэтому итог
 * прогрессии берётся из первого завершения, если экран его видел; сессия (оценка, заметка) — из последнего
 * ответа. Не видел (сессию завершили раньше — другое устройство, фоновая проекция, потерянный ответ завершения) —
 * честный ответ сервера: `already_completed` без итога, Summary о прогрессии ничего не утверждает.
 */
export function summaryResult(
  first: LiveSessionCompleteResponse | null, last: LiveSessionCompleteResponse,
): LiveSessionCompleteResponse {
  if (first === null) {
    return last;
  }
  return {
    ...last,
    progression_result: first.progression_result,
    progression_skipped_reason: first.progression_skipped_reason,
    course_progression: first.course_progression ?? null,
  };
}

/** Досрочное завершение (finish_early): сделанное сохраняется, занятие плана засчитывается, прогрессия НЕ
 * пересчитывается (недоделанные плановые подходы ⇒ abandoned на сервере). Оставшиеся подходы никуда не переносятся —
 * прежний текст «остальное останется в плане» обещал то, чего нет (аудит staging). */
export const FINISH_EARLY_HINT =
  "Сделанное сохранится в журнале; если тренировка из плана — занятие засчитается. Прогрессия не пересчитается, оставшиеся подходы не переносятся.";
