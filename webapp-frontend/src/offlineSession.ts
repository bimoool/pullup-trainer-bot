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
} from "./apiV2.ts";

const STORE_KEY = "pullup:v2:live-session";

/** "between" — клиентское имя серверного состояния "сессия стоит перед ещё не
 * начатым блоком" (awaiting_block_start): между блоками показывается
 * interstitial, следующий блок стартует только явным "Начать". */
export type LocalPhaseName = "get_ready" | "go" | "rest" | "between" | "done";

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
export function nextLocalPhase(
  current: LocalPhaseState,
  blockSetCounts: number[],
  manualTransitions = false,
): LocalPhaseState {
  if (current.phaseName === "done" || current.phaseName === "between") {
    // "between" покидается только явным startLiveBlock, не переходом фазы.
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
      // Builder-тренировка: следующий блок ждёт явного "Начать"; STEP и
      // legacy-комплексы идут по-старому (сразу get_ready следующего блока).
      return {
        phaseName: manualTransitions ? "between" : "get_ready",
        blockIndex: current.blockIndex + 1,
        setNumber: 1,
      };
    }
    return { phaseName: "rest", blockIndex: current.blockIndex, setNumber: current.setNumber };
  }

  // current.phaseName === "rest" -> get_ready следующего подхода того же блока.
  return { phaseName: "get_ready", blockIndex: current.blockIndex, setNumber: current.setNumber + 1 };
}

export function localPhaseDurationSeconds(phaseName: LocalPhaseName, restSeconds?: number | null): number | null {
  if (phaseName === "get_ready") {
    return GET_READY_SECONDS;
  }
  if (phaseName === "rest") {
    return restSeconds ?? DEFAULT_REST_SECONDS;
  }
  return null;
}

export interface QueuedSet {
  setIndex: number;
  /** Блок, в котором введён подход — сервер адресует запись блоком, не
   * только exercise_id (одно упражнение может повторяться в тренировке). */
  blockIndex: number;
  exerciseId: number;
  value: string;
  effort?: string | null;
  note?: string | null;
  /** #264 — подход сверх плана: не цель, фазу не двигает, прогрессией игнорируется. */
  isExtra?: boolean;
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
  completeRequested: { abandoned: boolean; effort?: string | null; comment?: string | null } | null;
  /** #264 — пауза get_ready/rest: сколько мс отсчёта осталось на момент паузы.
   * Только клиентское состояние (сервер таймер не ведёт — ends_at лишь
   * подсказка отображения), живёт в этом снимке и переживает reload/фон. */
  pausedRemainingMs?: number | null;
  /** #264 — конец фазы после «Продолжить» (ISO): перекрывает server ends_at. */
  endsAtOverride?: string | null;
  /** #265 — подход, только что записанный «Готово»: на отдыхе его можно
   * поправить (значение/оценка/заметка). Правка уходит тем же set_index —
   * сервер перезаписывает строку, дубля нет. Очищается при выходе из отдыха. */
  lastLogged?: QueuedSet | null;
}

/** #265 — отдых от стольки секунд достаточно длинный, чтобы панель записи
 * подхода раскрывалась сама; короче — свёрнута, раскрывается вручную. */
export const REST_PANEL_EXPAND_MIN_SECONDS = 20;
/** #265 — в последние стольки секунд отдыха показывается «Приготовься». */
export const GET_READY_CUE_SECONDS = 10;

export function restPanelExpandedByDefault(restSeconds: number | null | undefined): boolean {
  return (restSeconds ?? DEFAULT_REST_SECONDS) >= REST_PANEL_EXPAND_MIN_SECONDS;
}

/** Сигнал «Приготовься» — только на отдыхе и только в его последние 10 с. */
export function isGetReadyCueActive(phaseName: LocalPhaseName, remainingSeconds: number | null): boolean {
  return phaseName === "rest" && remainingSeconds !== null && remainingSeconds <= GET_READY_CUE_SECONDS;
}

export interface LastSetEdit {
  value: string;
  effort: string | null;
  note: string | null;
}

/** Правка только что записанного подхода: заменяет его запись в очереди
 * (или ставит ту же запись заново, если она уже ушла на сервер — тот же
 * set_index перезапишет строку). Пустое значение или отсутствие подхода —
 * без изменений; совпадающие значения — тоже (лишней синхронизации нет). */
export function editLastLoggedSet(local: LocalLiveSession, edit: LastSetEdit): LocalLiveSession {
  const last = local.lastLogged;
  const value = edit.value.trim();
  const note = edit.note?.trim() || null;
  if (!last || value === "") {
    return local;
  }
  if (last.value === value && (last.effort ?? null) === edit.effort && (last.note ?? null) === note) {
    return local;
  }
  const patched: QueuedSet = { ...last, value, effort: edit.effort, note };
  return {
    ...local,
    lastLogged: patched,
    pendingSets: [...local.pendingSets.filter((entry) => entry.setIndex !== patched.setIndex), patched],
  };
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

/** Локальный черновик можно переиспользовать только если он относится к
 * той же сессии и либо ещё несёт неотправленное, либо не отстаёт от
 * серверного состояния. Иначе (сессия ушла вперёд без нас — например,
 * прошёл interval-блок, где IndexedDB не используется) старый снимок
 * "протёк" бы в следующий блок. */
export function isLocalSessionReusable(existing: LocalLiveSession | null, session: LiveSessionResponse): boolean {
  if (existing === null || existing.serverSessionId !== session.id) {
    return false;
  }
  const hasPending =
    existing.pendingSets.length > 0 || existing.pendingPhaseAdvances > 0 || existing.completeRequested !== null;
  return hasPending || existing.server.phase_index === session.phase_index;
}

/** Ручной старт блоков — только у Builder-сессий: там каждый блок несёт
 * protocol_type из замороженного снимка (у STEP/legacy — null). */
export function hasManualTransitions(server: LiveSessionResponse): boolean {
  return server.blocks.length > 0 && server.blocks.every((block) => block.protocol_type !== null);
}

export function blockSetCounts(server: LiveSessionResponse): number[] {
  return server.blocks.map((block) => block.targets.length);
}

export function initialLocalSession(clientSessionId: string, server: LiveSessionResponse): LocalLiveSession {
  return {
    clientSessionId,
    serverSessionId: server.id,
    server,
    localPhase: {
      phaseName: server.awaiting_block_start ? "between" : server.phase.name,
      blockIndex: server.current_block_index,
      setNumber: server.current_set_number,
    },
    localPhaseEnteredAt: new Date().toISOString(),
    nextSetIndex: server.blocks.reduce((sum, block) => sum + block.set_logs.length, 0),
    pendingSets: [],
    pendingPhaseAdvances: 0,
    completeRequested: null,
  };
}

/** Конец текущей фазы в мс (epoch) — из `ends_at` сервера, пока локальная
 * фаза не убежала вперёд оптимистичным переходом, иначе из момента входа в
 * локальную фазу + её длительность. Чистая функция от сохранённого снимка, а
 * не от "сейчас": после возврата из фона/перезагрузки остаток считается как
 * `endsAt - Date.now()`, а не начинается заново. */
export function localPhaseEndsAtMs(local: LocalLiveSession): number | null {
  if (isLocalPaused(local)) {
    return null;
  }
  if (local.endsAtOverride) {
    return new Date(local.endsAtOverride).getTime();
  }
  if (local.pendingPhaseAdvances === 0 && local.server.phase.ends_at !== null) {
    return new Date(local.server.phase.ends_at).getTime();
  }
  const duration = localPhaseDurationSeconds(
    local.localPhase.phaseName, local.server.blocks[local.localPhase.blockIndex]?.rest_seconds,
  );
  return duration !== null ? new Date(local.localPhaseEnteredAt).getTime() + duration * 1000 : null;
}

export function isLocalPaused(local: LocalLiveSession): boolean {
  return local.pausedRemainingMs !== null && local.pausedRemainingMs !== undefined;
}

/** Паузу можно поставить только на обратный отсчёт (приготовься/отдых). Фаза
 * «пошёл» — работа пользователя без таймера, interval-блоки живут на
 * серверных часах и сюда (SessionLiveScreen) не попадают вовсе. */
export function canPauseLocal(local: LocalLiveSession): boolean {
  const name = local.localPhase.phaseName;
  return (name === "get_ready" || name === "rest") && !isLocalPaused(local);
}

/** Замораживает отсчёт: остаток считается от того же источника, что и
 * таймер на экране (localPhaseEndsAtMs). */
export function pauseLocalSession(local: LocalLiveSession, nowMs: number): LocalLiveSession {
  if (!canPauseLocal(local)) {
    return local;
  }
  const endsAt = localPhaseEndsAtMs(local);
  const remaining = endsAt === null ? 0 : Math.max(0, endsAt - nowMs);
  return { ...local, pausedRemainingMs: remaining, endsAtOverride: null };
}

export function resumeLocalSession(local: LocalLiveSession, nowMs: number): LocalLiveSession {
  if (!isLocalPaused(local)) {
    return local;
  }
  return {
    ...local, pausedRemainingMs: null, endsAtOverride: new Date(nowMs + (local.pausedRemainingMs ?? 0)).toISOString(),
  };
}

/** Снимает паузу/override при смене фазы (переход, запись подхода). */
export function clearPauseState(local: LocalLiveSession): LocalLiveSession {
  return { ...local, pausedRemainingMs: null, endsAtOverride: null };
}

/** Блок, к которому относится «+ Ещё подход»: последний завершённый
 * (done — текущий, between — предыдущий). null — предлагать нечего. */
export function extraSetBlockIndex(local: LocalLiveSession): number | null {
  const { phaseName, blockIndex } = local.localPhase;
  const index = phaseName === "between" ? blockIndex - 1 : phaseName === "done" ? blockIndex : -1;
  const block = local.server.blocks[index];
  if (block === undefined || block.exercise_id === null || block.protocol_type === "interval") {
    return null;
  }
  return index;
}

export function hasPendingWork(local: LocalLiveSession): boolean {
  return local.pendingSets.length > 0 || local.pendingPhaseAdvances > 0 || local.completeRequested !== null;
}

/**
 * Ответ сервера на флаш снимка `flushed` заменяет локальное состояние (см.
 * докстринг модуля) — но пока флаш был в полёте, пользователь мог добавить
 * новое (тап "Завершить" в окне реконнекта, подход, переход фазы). Это
 * новое не должно потеряться вместе со старым снимком: поверх свежего
 * серверного состояния переносится только то, что появилось ПОСЛЕ `flushed`.
 */
export function rebaseLocalSession(
  flushed: LocalLiveSession,
  current: LocalLiveSession,
  server: LiveSessionResponse,
): LocalLiveSession {
  const fresh = initialLocalSession(current.clientSessionId, server);
  // #265: правка уже отправленного подхода — запись со старым set_index, но
  // иным содержимым, чем в флаше; её тоже нельзя потерять.
  const flushedByIndex = new Map(flushed.pendingSets.map((entry) => [entry.setIndex, JSON.stringify(entry)]));
  const newerSets = current.pendingSets.filter(
    (entry) => entry.setIndex >= flushed.nextSetIndex || flushedByIndex.get(entry.setIndex) !== JSON.stringify(entry),
  );
  const newerAdvances = Math.max(0, current.pendingPhaseAdvances - flushed.pendingPhaseAdvances);
  // #264: пауза/override — клиентские; сервер побеждает по ИДЕНТИЧНОСТИ фазы:
  // фаза та же (номер перехода и позиция) — пауза переносится, иначе сброшена.
  const samePhase =
    fresh.server.phase_index === current.server.phase_index
    && fresh.localPhase.phaseName === current.localPhase.phaseName
    && fresh.localPhase.blockIndex === current.localPhase.blockIndex
    && fresh.localPhase.setNumber === current.localPhase.setNumber;
  const rebased = {
    ...fresh,
    completeRequested: current.completeRequested,
    pausedRemainingMs: samePhase ? current.pausedRemainingMs ?? null : null,
    endsAtOverride: samePhase ? current.endsAtOverride ?? null : null,
    lastLogged: current.lastLogged ?? null,
  };
  if (newerSets.length === 0 && newerAdvances === 0) {
    return rebased;
  }
  return {
    ...rebased,
    localPhase: current.localPhase,
    localPhaseEnteredAt: current.localPhaseEnteredAt,
    nextSetIndex: Math.max(fresh.nextSetIndex, current.nextSetIndex),
    pendingSets: newerSets,
    pendingPhaseAdvances: newerAdvances,
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
        block_index: entry.blockIndex,
        exercise_id: entry.exerciseId,
        value: entry.value,
        effort: entry.effort ?? null,
        note: entry.note ?? null,
        ...(entry.isExtra ? { is_extra: true } : {}),
      })),
    );
  }

  if (local.completeRequested) {
    return completeLiveSession(initDataRaw, local.serverSessionId, local.completeRequested.abandoned, {
      effort: local.completeRequested.effort ?? null,
      comment: local.completeRequested.comment ?? null,
    });
  }

  return server;
}
