/**
 * #306 F1 — ворота «очереди движка v2 сверены с сервером».
 *
 * Сервер лениво проецирует дедлайны сессии в двух чтениях: GET /sessions/live/active и список сессий
 * (GET /sessions). Если такое чтение опередит сохранённые офлайн-события пользователя (Стоп в 20 с,
 * пауза), они станут устаревшими no-op, а подход на время запишется целью. Поэтому, пока идёт сверка
 * очередей (`startEngineReconciliation` в liveEngineClient.ts, с повторами при временных сбоях), эти чтения
 * ждут её завершения (`awaitEngineReconciliation` в apiV2.ts). Модуль без зависимостей — его импортирует
 * apiV2.ts, а сверка сама пользуется apiV2.ts (без цикла импортов).
 */

let current: Promise<void> | null = null;

/** Сверка началась: чтения с проекцией ждут `done`. */
export function holdEngineReconciliation(done: Promise<void>): void {
  current = done;
  void done.catch(() => undefined).finally(() => {
    if (current === done) {
      current = null;
    }
  });
}

/** Нет сверки — сразу; идёт — дождаться (и следующей, если её начали, пока ждали). */
export async function awaitEngineReconciliation(): Promise<void> {
  let seen: Promise<void> | null = null;
  while (current !== null && current !== seen) {
    seen = current;
    await seen.catch(() => undefined);
  }
}
