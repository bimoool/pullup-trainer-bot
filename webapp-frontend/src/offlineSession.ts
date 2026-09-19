/**
 * Офлайн-слой живой сессии (issue #185, волна 5, `.claude/skills/offline-session/SKILL.md`).
 *
 * Разделение ролей трёх библиотек из скилла — сознательное, не буквальное
 * "react-query делает всё":
 *  - `idb-keyval` хранит САМ офлайн-лог (черновик активной сессии + очередь
 *    неотправленных подходов/переходов фазы) — это единственные данные,
 *    которые обязаны пережить закрытие Mini App посреди тренировки без сети
 *    (см. docs/plan-and-specs.md 10.8 "Прерывание"). Такой объём и время
 *    жизни (вся тренировка, возможно возобновлённая после рестарта) не
 *    подходят для localStorage (синхронный, маленький лимит).
 *  - `@tanstack/react-query` + `@tanstack/query-sync-storage-persister"
 *    (см. OfflineQueryProvider.tsx) переживают reload кэш GET-запросов
 *    (план/статус дашборда) — обычное, синхронное по объёму использование
 *    persistQueryClient, не сам офлайн-лог.
 * Это НЕ второй, самопальный слой синхронизации поверх готовых библиотек:
 * сами HTTP-вызовы (apiV2.ts) и контракт идемпотентности — целиком на
 * сервере (раздел 12 плана); этот модуль только решает, КОГДА их звать
 * (сразу, если онлайн, из очереди — когда сеть вернулась).
 */

import { del, get, set } from "idb-keyval";

import {
  advanceLiveSessionPhase,
  batchLiveSessionSets,
  completeLiveSession,
  type LiveSessionCompleteResponse,
  type LiveSessionResponse,
} from "./apiV2";

const STORE_KEY = "pullup:v2:live-session";

export type LocalPhaseName = "get_ready" | "go" | "rest" | "done";

export interface LocalPhaseState {
  phaseName: LocalPhaseName;
  blockIndex: number;
  setNumber: number;
}

// Зеркало продуктовых констант app/domain/live_session.py (GET_READY_SECONDS/
// DEFAULT_REST_SECONDS) — используется ТОЛЬКО для локальной оценки обратного
// отсчёта, пока сервер недоступен (раздел 11 плана: "клиент — источник
// правды по введённым значениям до синхронизации", НЕ по ends_at — тем
// сервер остаётся единственным источником правды, offline-session skill).
// Если продуктовые числа в домене поменяются, эта копия расходится молча —
// открытый, осознанно принятый риск дублирования ради простоты (нет общего
// пакета констант между Python-бэкендом и TS-фронтендом в проекте).
const GET_READY_SECONDS = 5;
const DEFAULT_REST_SECONDS = 90;

/** Чистая функция-зеркало app.domain.live_session.next_phase — та же логика
 * переходов, нужна фронтенду только для того, чтобы РИСОВАТЬ следующий шаг,
 * пока ответ сервера ещё не пришёл (офлайн) или в полёте (онлайн, до ответа
 * — оптимистичный UI). Как только ответ сервера приходит, он ЗАМЕНЯЕТ этот
 * локальный расчёт целиком (см. flushLocalSession ниже), а не мёржится с ним. */
export function nextLocalPhase(current: LocalPhaseState, blockSetCounts: number[]): LocalPhaseState {
  if (current.phaseName === "done") {
    return current;
  }
  if (blockSetCounts.length === 0 || current.blockIndex >= blockSetCounts.length) {
    return { phaseName: "done", blockIndex: current.blockIndex, setNumber: current.setNumber };
  }
  const setsCount = blockSetCounts[current.blockIndex];

  if (current.phaseName === "get_ready") {
    return { phaseName: "go", blockIndex: current.blockIndex, setNumber: current.setNumber };
  }

  if (current.phaseName === "go") {
    const isLastSetOfBlock = current.setNumber >= setsCount;
    const isLastBlock = current.blockIndex >= blockSetCounts.length - 1;
    if (isLastSetOfBlock && isLastBlock) {
      return { phaseName: "done", blockIndex: current.blockIndex, setNumber: current.setNumber };
    }
    if (isLastSetOfBlock) {
      return { phaseName: "get_ready", blockIndex: current.blockIndex + 1, setNumber: 1 };
    }
    return { phaseName: "rest", blockIndex: current.blockIndex, setNumber: current.setNumber };
  }

  // current.phaseName === "rest" -> get_ready следующего подхода того же блока.
  return { phaseName: "get_ready", blockIndex: current.blockIndex, setNumber: current.setNumber + 1 };
}

export function localPhaseDurationSeconds(phaseName: LocalPhaseName): number | null {
  if (phaseName === "get_ready") {
    return GET_READY_SECONDS;
  }
  if (phaseName === "rest") {
    return DEFAULT_REST_SECONDS;
  }
  return null;
}

export interface QueuedSet {
  setIndex: number;
  exerciseId: number;
  value: string;
  effort?: string | null;
  note?: string | null;
}

/** Черновик активной живой сessии в IndexedDB — ровно одна запись (та же
 * инвариантность "одна активная сессия", что GET /sessions/live/active на
 * сервере). `server` — последний ПОДТВЕРЖДЁННЫЙ сервером снимок; локальные
 * поля ниже — оптимистичная надстройка поверх него, которая исчезает целиком
 * при успешном flushLocalSession (см. докстринг модуля). */
export interface LocalLiveSession {
  clientSessionId: string;
  serverSessionId: number;
  server: LiveSessionResponse;
  localPhase: LocalPhaseState;
  /** Момент входа в localPhase (ISO) — обратный отсчёт всегда считается от
   * него по локальным константам (GET_READY_SECONDS/DEFAULT_REST_SECONDS)
   * ОДИНАКОВО онлайн и офлайн: длительности фиксированы контрактом (не
   * зависят от нагрузки сервера), так что дублирования "двух разных
   * таймеров" не возникает — сервер остаётся источником правды для ЧИСЕЛ
   * подходов/фаз (phase_index и т.п.), не для миллисекунд отображения. */
  localPhaseEnteredAt: string;
  nextSetIndex: number;
  pendingSets: QueuedSet[];
  pendingPhaseAdvances: number;
  completeRequested: { abandoned: boolean } | null;
}

export async function loadLocalSession(): Promise<LocalLiveSession | null> {
  const value = await get<LocalLiveSession>(STORE_KEY);
  return value ?? null;
}

export async function saveLocalSession(local: LocalLiveSession): Promise<void> {
  await set(STORE_KEY, local);
}

export async function clearLocalSession(): Promise<void> {
  await del(STORE_KEY);
}

export function blockSetCounts(server: LiveSessionResponse): number[] {
  return server.blocks.map((block) => block.targets.length);
}

export function initialLocalSession(clientSessionId: string, server: LiveSessionResponse): LocalLiveSession {
  return {
    clientSessionId,
    serverSessionId: server.id,
    server,
    localPhase: { phaseName: server.phase.name, blockIndex: server.current_block_index, setNumber: server.current_set_number },
    localPhaseEnteredAt: new Date().toISOString(),
    nextSetIndex: server.blocks.reduce((sum, block) => sum + block.set_logs.length, 0),
    pendingSets: [],
    pendingPhaseAdvances: 0,
    completeRequested: null,
  };
}

/**
 * Досылает всё, что накопилось локально, пока сети не было (или пока не
 * дождались ответа) — переходы фазы по порядку, затем батч подходов одним
 * запросом (раздел 12: "это основной офлайн-эндпоинт"), затем complete, если
 * пользователь просил завершить. `expected_phase_index` для каждого
 * перехода берётся из ПОСЛЕДНЕГО известного ответа сервера — если сервер
 * уже дальше (это повтор дошедшего раньше запроса), он просто вернёт текущее
 * состояние без изменений (офлайн-контракт, `advance_phase` на бэкенде).
 */
export async function flushLocalSession(
  initDataRaw: string,
  local: LocalLiveSession,
): Promise<LiveSessionResponse | LiveSessionCompleteResponse> {
  let server = local.server;

  for (let i = 0; i < local.pendingPhaseAdvances; i += 1) {
    server = await advanceLiveSessionPhase(initDataRaw, local.serverSessionId, server.phase_index);
  }

  if (local.pendingSets.length > 0) {
    server = await batchLiveSessionSets(
      initDataRaw,
      local.serverSessionId,
      local.pendingSets.map((entry) => ({
        set_index: entry.setIndex,
        exercise_id: entry.exerciseId,
        value: entry.value,
        effort: entry.effort ?? null,
        note: entry.note ?? null,
      })),
    );
  }

  if (local.completeRequested) {
    return completeLiveSession(initDataRaw, local.serverSessionId, local.completeRequested.abandoned);
  }

  return server;
}
