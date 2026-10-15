import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useRef, useState } from "react";

import {
  completeLiveSession, fetchActiveLiveSession, postLiveEngineEvents,
  type LiveSessionCompleteResponse, type LiveSessionResponse,
} from "./apiV2";
import { formatDuration, formatLoggedSetSummary, formatNumber } from "./blockFormat";
import { isCompleteDecimal, sanitizeDecimalInput } from "./decimalInput";
import { EFFORT_SCALE, WORKOUT_COMMENT_MAX } from "./effortScale";
import { carriesCompletionOutcome, classifySyncError, FINISH_EARLY_HINT, summaryResult, type SyncFailure } from "./liveFinish";
import {
  activeElapsedMs, remainingMs, type CheckAnswer, type EnginePlan, type EngineState, type Phase, type PlanBlock,
} from "./liveEngine";
import {
  claimQueue, createQueueOwner, createScreenLifecycle, createSyncRetry, displayState, dropAcknowledged, emptyQueue,
  newEvent, releaseQueue, serverOffsetMs, startEngineReconciliation,
  type EngineQueue, type QueueOwner, type QueuedEngineEvent,
} from "./liveEngineClient";
import { cancelScheduledPhaseEndSound, phaseEndCueDelaySeconds, schedulePhaseEndSound } from "./phaseAudio";
import { confirmAction } from "./telegramPlatform";
import { useBackButton } from "./useBackButton";
import { isTextEntryTarget, useLiveFieldFocus } from "./liveFieldFocus";
import { useClosingConfirmation } from "./useClosingConfirmation";
import { vibratePhaseEnd, vibrationDelayMs } from "./vibration";
import { disableWakeLock, enableWakeLock } from "./wakeLock";

type Props = {
  initDataRaw: string;
  initialSession: LiveSessionResponse;
  onCompleted: (result: LiveSessionCompleteResponse) => void;
  /** Уйти с экрана (Back, отмена): сессия на сервере продолжается, App возобновит её при открытии. */
  onLeave: () => void;
  resolveExerciseName?: (exerciseId: number) => string | null;
  title?: string;
};

/** Повторная сверка с сервером, пока экран открыт (второе устройство, пауза с другого телефона). */
const RESYNC_INTERVAL_MS = 15_000;
const GET_READY_CUE_SECONDS = 10;

/** CSS-фаза live.css (цвета/подписи общие с экраном движка v1). */
const PHASE_CSS: Record<Phase, string> = {
  PREP: "get_ready", WORK: "go", RESULT: "go", REST: "rest", CONFIRM: "done", COMPLETE: "done",
};

type BlockAnswers = { technique: CheckAnswer; rest: CheckAnswer };

/** #305 V5.6 §11: блоки, по которым нужен ответ о технике и отдыхе (план просит, блок начат). */
function blocksToConfirm(plan: EnginePlan, state: EngineState): number[] {
  return plan.blocks
    .map((block, index) => (block.confirm_checks && state.logs.some((log) => log.block_index === index) ? index : -1))
    .filter((index) => index >= 0);
}

/** Серверные факты: блок остановлен «техника нарушена»; в отдыхе между подходами была пауза. */
const techniqueStopped = (state: EngineState, index: number): boolean =>
  (state.stopped_blocks ?? []).some((entry) => entry.block_index === index && entry.reason === "technique");
/** Открытая правка записанного подхода: адрес лога фиксируется при открытии, а не берётся из «последнего» на момент
 * сохранения — после смены фазы последним может стать уже другой подход. */
type SetEdit = { block_index: number; set_index: number; round_index: number | null; value: string };

const restPaused = (state: EngineState, index: number): boolean => (state.rest_paused ?? []).includes(index);

function checksPayload(indexes: number[], answers: Record<number, BlockAnswers>) {
  return indexes.map((index) => ({
    block_index: index, technique: answers[index]?.technique ?? null, rest: answers[index]?.rest ?? null,
  }));
}

/**
 * Live-экран движка v2 (issue #306, LIVE_ENGINE_V2): проекция серверного состояния. Переходы по
 * дедлайнам (PREP → WORK, REST → WORK, отдых блока → следующий блок) делает сервер; экран лишь рисует
 * тот же детерминированный `project` между ответами и шлёт события пользователя. Кнопок «Готов» /
 * «Пропустить отдых» / «Начать» между блоками нет: вторичное «Начать сейчас» — событие skip_wait.
 * Пауза — серверное событие (переживает reload и второе устройство).
 */
export function LiveEngineScreen({ initDataRaw, initialSession, onCompleted, onLeave, resolveExerciseName, title }: Props) {
  const [server, setServer] = useState<LiveSessionResponse>(initialSession);
  const [offset, setOffset] = useState(() => (initialSession.engine ? initialSession.engine.server_time_ms - Date.now() : 0));
  const [queue, setQueueState] = useState<EngineQueue>(() => emptyQueue(initialSession.id));
  const queueRef = useRef(queue);
  const [ready, setReady] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [online, setOnline] = useState(navigator.onLine);
  const [failure, setFailure] = useState<SyncFailure | null>(null);
  const [value, setValue] = useState("");
  const [extraOpen, setExtraOpen] = useState(false);
  const [extraValue, setExtraValue] = useState("");
  // Правка записанного подхода живёт отдельно от фазы: переход отдыха в работу её не закрывает и не теряет введённое
  // (аудит staging 6475bc0). Закрывают только «Сохранить подход» и «Отменить правку».
  const [edit, setEdit] = useState<SetEdit | null>(null);
  // Аудит staging 7500c37 (320×640): как у движка v1 (M1, #285) — пока поле в фокусе, транспорт не липнет к низу и
  // не закрывает поле под экранной клавиатурой.
  const fieldFocused = useLiveFieldFocus();
  const logPanelRef = useRef<HTMLElement | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewEffort, setReviewEffort] = useState<string | null>(null);
  const [reviewComment, setReviewComment] = useState("");
  const [answers, setAnswers] = useState<Record<number, BlockAnswers>>({});
  const syncing = useRef<Promise<void> | null>(null);
  const resync = useRef(false);
  const firstCompletion = useRef<LiveSessionCompleteResponse | null>(null);
  const closed = useRef(false);
  // Временный сбой досылки при браузере «онлайн»: повтор сам, с растущей паузой (createSyncRetry).
  const [retry] = useState(() => createSyncRetry(() => void sync()));
  // Аудит #322: после ухода/unmount/смены сессии поздний ответ старой досылки ничего не планирует и не шлёт.
  const [lifecycle] = useState(createScreenLifecycle);
  // Очередь сессии пишется только через владельца: до достоверного чтения сохранённой очереди запись
  // отклоняется (непрочитанные недосланные события не затираются). Сбой чтения — не «пусто»: ввод
  // заблокирован с объяснением, чтение повторяется само (1, 2, 4, 8, 15 с) и по «Повторить».
  const owner = useRef<QueueOwner>(createQueueOwner(initialSession.id));  // заменяется в эффекте сессии
  const [queueUnreadable, setQueueUnreadable] = useState(false);
  const loadNow = useRef<() => void>(() => undefined);
  const [loadRetry] = useState(() => createSyncRetry(() => loadNow.current()));
  // MVP «сохранность результата»: действие (подход, пауза, завершение…) экран подтверждает — новая фаза, «Подход N: …»
  // — только ПОСЛЕ записи очереди на устройство. Раньше экран обновлялся до записи: закрыли приложение в этом окне —
  // подтверждённый результат пропадал. Все записи очереди идут по одной, в порядке вызова, и каждая пишет актуальную
  // очередь — поздняя запись не затирает более новую. Пока запись идёт — «Сохраняю…» и действия недоступны; сбой
  // записи — введённое остаётся, «Повторить» пишет то же событие (тот же client_event_id и время нажатия).
  const writes = useRef<Promise<unknown>>(Promise.resolve());
  const savingRef = useRef(0);
  const [saving, setSaving] = useState(false);
  const [saveFailure, setSaveFailure] = useState<{ retry: () => void } | null>(null);

  const engine = server.engine;
  const plan = engine?.plan ?? null;
  const nowServer = now + offset;
  const state: EngineState | null = plan && engine ? displayState(plan, engine.state, queue.events, nowServer) : null;

  function setQueue(next: EngineQueue) {
    queueRef.current = next;
    setQueueState(next);
  }

  /** Запись очереди в общем порядке записей (ошибка предыдущей не блокирует следующую). */
  function chainWrite<T>(write: () => Promise<T>): Promise<T> {
    const run = writes.current.catch(() => undefined).then(write);
    writes.current = run;
    return run;
  }

  /**
   * Добавить события (и/или завершение) в очередь: сначала запись на устройство, потом экран. Повторная запись тех же
   * событий (после сбоя) не дублирует их: события с известным client_event_id не добавляются.
   */
  async function commit(events: QueuedEngineEvent[], complete: EngineQueue["complete"] | undefined, onSaved?: () => void): Promise<boolean> {
    const add = (base: EngineQueue): EngineQueue => ({
      ...base,
      events: [...base.events, ...events.filter((event) => !base.events.some((known) => known.client_event_id === event.client_event_id))],
      complete: complete !== undefined ? complete : base.complete,
    });
    savingRef.current += 1;
    setSaving(true);
    setSaveFailure(null);
    try {
      await chainWrite(async () => {
        await owner.current.save(add(queueRef.current));
        setQueue(add(queueRef.current));  // записано — теперь экран может подтвердить
      });
    } catch {
      setSaveFailure({ retry: () => void commit(events, complete, onSaved) });
      return false;
    } finally {
      savingRef.current -= 1;
      setSaving(savingRef.current > 0);
    }
    setNow(Date.now());
    onSaved?.();
    void sync();
    return true;
  }

  function acceptServer(response: LiveSessionResponse, startedMs: number, receivedMs: number) {
    if (response.engine) {
      setOffset(serverOffsetMs(response.engine.server_time_ms, startedMs, receivedMs));
    }
    setServer(response);
    setNow(Date.now());
  }

  async function finishWith(result: LiveSessionCompleteResponse) {
    if (closed.current) {
      return;
    }
    closed.current = true;
    await chainWrite(() => owner.current.clear());  // после уже начатых записей: поздняя запись не вернёт очередь
    if (result.progression_skipped_reason === "cancelled" || result.engine_status === "cancelled") {
      onLeave();
      return;
    }
    onCompleted(summaryResult(firstCompletion.current, result));
  }

  function sync(): Promise<void> {
    retry.cancel();  // досылка идёт сейчас — отложенный повтор не нужен (не дублировать запрос)
    const token = lifecycle.token();
    if (token === null || !owner.current.loaded()) {
      return Promise.resolve();  // экран ушёл (очередь — у сверки App) или очередь ещё не прочитана
    }
    if (syncing.current !== null) {
      resync.current = true;
      return syncing.current;
    }
    const run = runSync(token).finally(() => {
      syncing.current = null;
      if (resync.current && !closed.current && lifecycle.token() !== null) {
        resync.current = false;
        void sync();
      }
    });
    syncing.current = run;
    return run;
  }

  async function runSync(token: number): Promise<void> {
    do {
      resync.current = false;
      if (closed.current || !navigator.onLine || !lifecycle.isCurrent(token)) {
        return;
      }
      const pending = queueRef.current;
      try {
        if (pending.events.length > 0) {
          const started = Date.now();
          const response = await postLiveEngineEvents(initDataRaw, pending.sessionId, pending.events.map((event) => ({
            client_event_id: event.client_event_id, type: event.type, payload: event.payload,
            client_at: new Date(event.client_at_ms).toISOString(),
          })));
          if (!lifecycle.isCurrent(token)) {
            return;  // поздний ответ ушедшего экрана: очередь не трогаем, App перешлёт (duplicate)
          }
          acceptServer(response, started, Date.now());
          if (firstCompletion.current === null && carriesCompletionOutcome(response)) {
            firstCompletion.current = response;
          }
          const rest = dropAcknowledged(queueRef.current, response.event_results.map((r) => r.client_event_id));
          setQueue(rest);
          await chainWrite(() => owner.current.save(queueRef.current));
          if (!lifecycle.isCurrent(token)) {
            return;
          }
          if (response.engine_status === "cancelled") {
            await finishWith(response);
            return;
          }
        }
        if (queueRef.current.complete !== null && queueRef.current.events.length === 0) {
          const review = queueRef.current.complete;
          const result = await completeLiveSession(initDataRaw, pending.sessionId, false, review);
          if (!lifecycle.isCurrent(token)) {
            return;  // завершение сохранено сервером; итог ушедшему экрану не показываем
          }
          await finishWith(result);
          return;
        }
        setFailure(null);
        retry.reset();
      } catch (error) {
        if (!lifecycle.isCurrent(token)) {
          return;  // сбой запроса ушедшего экрана: ни повтора, ни новой досылки — очередь у сверки App
        }
        const failure = classifySyncError(error);
        setFailure(failure);
        if (failure.kind === "transient" && !closed.current) {
          retry.schedule();
        }
        return;
      }
    } while (resync.current);
  }

  /** Сверка с сервером: свежая проекция (дедлайны, истёкшие в фоне, уже применены сервером). */
  async function refresh(): Promise<void> {
    const token = lifecycle.token();
    if (token === null || !navigator.onLine || closed.current || !owner.current.loaded() || queueRef.current.events.length > 0) {
      return;  // непрочитанная очередь может нести действие до дедлайна — проекцию не запрашиваем
    }
    try {
      const started = Date.now();
      const active = await fetchActiveLiveSession(initDataRaw);
      if (!lifecycle.isCurrent(token)) {
        return;
      }
      if (active !== null && active.id === initialSession.id) {
        acceptServer(active, started, Date.now());
        return;
      }
      // Не активна на сервере: завершилась сама (проекция в фоне), на другом устройстве или отменена.
      // Идемпотентный complete отдаёт итог, ничего не повторяя (#307 T).
      const result = await completeLiveSession(initDataRaw, initialSession.id, false);
      if (!lifecycle.isCurrent(token)) {
        return;
      }
      if (result.engine_status === "cancelled" || result.progression_skipped_reason === "cancelled") {
        await finishWith(result);
        return;
      }
      if (firstCompletion.current === null) {
        firstCompletion.current = result;
      }
      setServer(result);
    } catch (error) {
      if (lifecycle.isCurrent(token)) {
        setFailure(classifySyncError(error));
      }
    }
  }

  useEffect(() => {
    let cancelled = false;
    lifecycle.mount();
    // #306 F1: пока экран открыт, очередью этой сессии владеет он (сверка App её пропускает); после ухода
    // недосланное подхватывает сверка App (startEngineReconciliation).
    claimQueue(initialSession.id);
    const sessionOwner = createQueueOwner(initialSession.id);
    owner.current = sessionOwner;
    let loading = false;
    async function loadStored(): Promise<void> {
      const token = lifecycle.token();
      if (token === null || loading || sessionOwner.loaded()) {
        return;
      }
      const local = queueRef.current.sessionId === initialSession.id ? queueRef.current : emptyQueue(initialSession.id);
      loading = true;
      const merged = await sessionOwner.load(local).finally(() => {
        loading = false;
      });
      if (cancelled || !lifecycle.isCurrent(token)) {
        return;
      }
      if (merged === null) {
        setQueueUnreadable(true);  // сохранённое не прочитано: ввод заблокирован, повтор сам
        loadRetry.schedule();
        return;
      }
      loadRetry.reset();
      setQueueUnreadable(false);
      setQueue(merged);
      if (local.events.length > 0 || local.complete !== null) {
        await chainWrite(() => sessionOwner.save(queueRef.current));  // локальное (если было) — после сохранённого, без дублей
      }
      setReady(true);
      if (merged.events.length > 0 || merged.complete !== null) {
        void sync();
      } else {
        void refresh();
      }
    }
    loadNow.current = () => void loadStored();
    void loadStored();
    return () => {
      cancelled = true;
      lifecycle.unmount();  // до cancel: поздний сбой уже ушедшей досылки не поставит новый таймер
      retry.cancel();
      loadRetry.cancel();
      releaseQueue(initialSession.id);
      // Недосланное (сбой сети перед «Выйти») сверяет App. Старт — здесь, в очистке: React выполняет её раньше
      // эффектов экранов, которые монтируются следом, — их чтения с проекцией уже увидят ворота.
      void startEngineReconciliation(initDataRaw);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSession.id]);

  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 250);
    const poll = window.setInterval(() => void refresh(), RESYNC_INTERVAL_MS);
    function onVisible() {
      if (document.visibilityState === "visible") {
        setNow(Date.now());
        void (queueRef.current.events.length > 0 ? sync() : refresh());
      }
    }
    function onOnline() {
      setOnline(true);
      void sync();
    }
    function onOffline() {
      setOnline(false);
    }
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    enableWakeLock();
    return () => {
      window.clearInterval(tick);
      window.clearInterval(poll);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      disableWakeLock();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Аудио/вибро-хук (§6): сигнал конца фазы — из ЕДИНСТВЕННОГО дедлайна (часы клиента = − offset).
  // В фоне снимается; истёкшая в фоне фаза сигнала не даёт (P4). Сами звуки — вне #306.
  const deadlineClientMs = state?.phase_deadline_at != null ? state.phase_deadline_at - offset : null;
  useEffect(() => {
    if (deadlineClientMs === null) {
      cancelScheduledPhaseEndSound();
      return;
    }
    let vibration: ReturnType<typeof setTimeout> | null = null;
    function schedule() {
      if (vibration !== null) {
        clearTimeout(vibration);
      }
      const delay = phaseEndCueDelaySeconds(deadlineClientMs as number, Date.now());
      if (delay === null) {
        cancelScheduledPhaseEndSound();
        return;
      }
      schedulePhaseEndSound(delay);
      const vibrateIn = vibrationDelayMs(deadlineClientMs as number, Date.now());
      if (vibrateIn !== null) {
        vibration = setTimeout(() => {
          if (document.visibilityState === "visible") {
            vibratePhaseEnd();
          }
        }, vibrateIn);
      }
    }
    function onVisibility() {
      if (document.visibilityState === "visible") {
        schedule();
      } else {
        cancelScheduledPhaseEndSound();
      }
    }
    schedule();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      cancelScheduledPhaseEndSound();
      if (vibration !== null) {
        clearTimeout(vibration);
      }
    };
  }, [deadlineClientMs]);

  // Поле результата не переживает смену подхода (тот же принцип, что у движка v1, инвариант I).
  const cursorKey = state ? `${state.cursor.block_index}:${state.cursor.set_index}:${state.phase}` : "";
  useEffect(() => {
    if (state === null) {
      return;
    }
    const spec = plan?.blocks[state.cursor.block_index]?.sets?.[state.cursor.set_index];
    if (state.phase === "RESULT" && state.pending_value !== null) {
      setValue(String(state.pending_value));
    } else if (state.phase === "WORK" && spec?.kind === "reps" && spec.target !== null) {
      setValue(String(spec.target));
    } else {
      setValue("");
    }
    // Аудит staging 7500c37: на 320×640 поле результата оказывалось под липким транспортом — видна только подпись,
    // «Готово» неактивно, пока не прокрутишь. На входе в фазу ввода панель прокручивается в видимую область
    // (с учётом scroll-padding-bottom под транспорт, live.css); фокус не ставится — клавиатура не открывается сама.
    // Только когда панель действительно закрыта транспортом и пользователь ещё не вводит: иначе прокрутка сдвигает
    // «Готово» прямо под пальцем, и нажатие промахивается (локальная перепроверка plans-manual-session, ветка 352fd15).
    if (state.phase === "WORK" || state.phase === "RESULT") {
      requestAnimationFrame(() => {
        const panel = logPanelRef.current;
        if (panel === null || isTextEntryTarget(document.activeElement as HTMLElement | null)) {
          return;
        }
        const transport = document.querySelector(".live-transport");
        const visibleBottom = transport !== null ? transport.getBoundingClientRect().top : window.innerHeight;
        if (panel.getBoundingClientRect().bottom > visibleBottom) {
          panel.scrollIntoView?.({ block: "nearest" });
        }
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cursorKey]);

  useBackButton(() => {
    if (reviewOpen) {
      setReviewOpen(false);
    } else {
      onLeave();
    }
  }, [reviewOpen], true, false);
  useClosingConfirmation();

  /** Действие можно начать: очередь прочитана, предыдущая запись завершена и не упала (порядок событий). */
  const canAct = (): boolean => owner.current.loaded() && savingRef.current === 0 && saveFailure === null;

  async function enqueue(type: string, payload: Record<string, unknown>, onSaved?: () => void): Promise<boolean> {
    if (!canAct()) {
      return false;  // очередь не прочитана, запись ещё идёт или ждёт «Повторить»
    }
    // Время события — момент нажатия (дедлайны), а не момент записи.
    return commit([newEvent(type, payload, Date.now() + offset)], undefined, onSaved);
  }

  async function requestFinish(): Promise<void> {
    if (state === null || !canAct()) {
      return;
    }
    const review = { effort: reviewEffort, comment: reviewComment.trim() || null };
    // #305: ответы о технике/отдыхе (неотвеченное = неизвестно) — в payload finish_early, в журнал событий.
    const confirmIndexes = plan ? blocksToConfirm(plan, state) : [];
    const finishPayload = confirmIndexes.length > 0 ? { checks: checksPayload(confirmIndexes, answers) } : {};
    const events = state.status === "active" ? [newEvent("finish_early", finishPayload, Date.now() + offset)] : [];
    await commit(events, review, () => setReviewOpen(false));
  }

  async function requestCancel(): Promise<void> {
    if (!(await confirmAction("Отменить тренировку? Ничего не сохранится."))) {
      return;
    }
    setReviewOpen(false);
    await enqueue("cancel", {});
  }

  if (!ready && queueUnreadable) {
    return (
      <div className="error-banner" role="alert" data-testid="engine-queue-unreadable">
        <p>Не удалось прочитать сохранённые данные тренировки. Пробуем снова. Не очищайте данные приложения.</p>
        <p>Пока они не прочитаны, действия тренировки недоступны: новое действие могло бы затереть сохранённое.</p>
        <button type="button" className="action-button" data-testid="engine-queue-retry" onClick={() => { loadRetry.cancel(); loadNow.current(); }}>
          Повторить
        </button>
      </div>
    );
  }
  if (!ready || state === null || plan === null) {
    return <p className="screen-message">Загружаю тренировку…</p>;
  }

  const block: PlanBlock = plan.blocks[state.cursor.block_index];
  const isInterval = block.kind === "interval";
  const spec = isInterval ? null : block.sets?.[state.cursor.set_index] ?? null;
  const remaining = remainingMs(state, nowServer);
  const paused = state.paused_at !== null;
  const finishing = queue.complete !== null;
  const blockName = (index: number): string | null => {
    const candidate = server.blocks[index];
    if (!candidate) {
      return null;
    }
    if (candidate.exercise_name) {
      return candidate.exercise_name;
    }
    return candidate.exercise_id !== null && resolveExerciseName ? resolveExerciseName(candidate.exercise_id) : null;
  };
  const totalUnits = isInterval ? block.interval?.rounds ?? 0 : block.sets?.length ?? 0;
  const unitNumber = (isInterval ? state.cursor.round_index ?? 0 : state.cursor.set_index) + 1;
  const isBlockRest = state.phase === "REST" && state.rest_kind === "block";
  const nextBlockIndex = isBlockRest ? state.cursor.block_index + 1 : null;
  const lastLog = [...state.logs].reverse().find((log) => !log.is_extra && log.value !== null) ?? null;
  const lastLogPanel = lastLog !== null && state.phase !== "COMPLETE" && !finishing && (state.phase === "REST" || state.phase === "PREP");
  // Открытая правка видна в любой фазе, пока тренировка не завершается. Нижняя панель на это время не липнет к низу
  // (как при фокусе поля): на узком экране она перекрывала «Сохранить подход» (аудит staging, 320×568), но скрывать её
  // целиком нельзя — «Пауза» должна оставаться доступной.
  const editPanelOpen = edit !== null && !finishing;
  const logLabel = (log: { block_index: number; set_index: number }): string => {
    const kind = plan.blocks[log.block_index]?.sets?.[log.set_index]?.kind;
    return kind === "time" || kind === "max_time" ? "Секунды" : "Повторений";
  };
  const timedWork = state.phase === "WORK" && (isInterval || spec?.kind === "time");
  const countUp = state.phase === "WORK" && spec?.kind === "max_time";
  const workInput = state.phase === "WORK" && !isInterval && (spec?.kind === "reps" || spec?.kind === "max_reps");
  const resultInput = state.phase === "RESULT";
  const showSkip = state.phase === "PREP" || state.phase === "REST" || (state.phase === "RESULT" && isInterval);
  const extraBlockIndex = state.status === "completed"
    ? plan.blocks.length - 1
    : isBlockRest ? state.cursor.block_index : null;
  const extraAllowed = extraBlockIndex !== null && plan.blocks[extraBlockIndex].kind === "sets"
    && (plan.blocks[extraBlockIndex].extra_sets_allowed ?? true);
  const pendingCount = queue.events.length + (finishing ? 1 : 0);
  const busy = saving || saveFailure !== null;  // запись идёт или ждёт «Повторить»: новые действия нарушили бы порядок
  const saveErrorBanner = saveFailure !== null && (
    <div className="error-banner" role="alert" data-testid="engine-save-error">
      <p>Не удалось сохранить действие на устройстве. Введённое не потеряно — нажмите «Повторить».</p>
      <button type="button" className="action-button" onClick={saveFailure.retry}>Повторить</button>
    </div>
  );
  const phaseLabel = state.phase === "PREP" ? "Приготовься"
    : state.phase === "WORK" ? "Пошёл"
      : state.phase === "RESULT" ? (isInterval ? "Повторы раунда" : "Результат")
        : state.phase === "REST" ? "Отдых"
          : state.phase === "CONFIRM" ? "Техника и отдых" : "Готово";
  const confirmIndexes = blocksToConfirm(plan, state);
  const stopRule = !isInterval && block.stop_at_or_below != null ? block.stop_at_or_below : null;
  const cap = spec?.cap ?? null;
  const overCap = cap !== null && isCompleteDecimal(value) && Number(value) > cap;
  const remainingSeconds = remaining !== null ? remaining / 1000 : null;
  const getReadyCue = state.phase === "REST" && remainingSeconds !== null && !paused && remainingSeconds <= GET_READY_CUE_SECONDS;

  const submit = (event?: React.FormEvent, technique?: "invalid") => {
    event?.preventDefault();
    if (!isCompleteDecimal(value)) {
      return;
    }
    void enqueue("submit_result", {
      block_index: state.cursor.block_index, set_index: state.cursor.set_index, round_index: state.cursor.round_index,
      value: Number(value), ...(technique ? { technique } : {}),
    });
  };
  const answerOf = (index: number): BlockAnswers => answers[index] ?? { technique: null, rest: null };
  const setAnswer = (index: number, key: keyof BlockAnswers, answer: CheckAnswer) =>
    setAnswers((current) => ({ ...current, [index]: { ...answerOf(index), [key]: answer } }));
  const checksForm = confirmIndexes.length > 0 && (
    <BlockChecks
      indexes={confirmIndexes} plan={plan} state={state} answerOf={answerOf} onAnswer={setAnswer} blockName={blockName}
    />
  );

  return (
    <div
      className="live-screen" data-phase={PHASE_CSS[state.phase]} data-engine-phase={state.phase}
      data-paused={paused ? "true" : undefined} data-set-edit={editPanelOpen ? "true" : undefined}
      data-field-focus={fieldFocused ? "true" : undefined}
    >
      <header className="live-header">
        <div className="live-header-text">
          <p className="live-eyebrow">Живая тренировка</p>
          {title && <p className="live-workout-title">{title}</p>}
        </div>
        {state.status === "active" && state.phase !== "CONFIRM" && !finishing && (
          <button type="button" className="live-finish" data-testid="engine-finish" onClick={() => setReviewOpen(true)}>
            Завершить
          </button>
        )}
      </header>
      {!online && <p className="gap-banner">Нет сети — действия сохраняются на устройстве и уйдут при подключении.</p>}
      {saving && <p className="gap-banner" role="status" data-testid="engine-saving">Сохраняю на устройстве…</p>}
      {saveErrorBanner}
      {online && pendingCount > 0 && <p className="gap-banner" data-testid="engine-pending">Не синхронизировано: {pendingCount}. Досылаю…</p>}
      {failure && (
        <p className="gap-banner" data-testid="engine-sync-error">
          Не удалось синхронизировать: {failure.message}.{failure.kind === "transient" && online ? " Повторю сам." : ""}{" "}
          <button type="button" className="live-link-button" onClick={() => void sync()}>Повторить</button>
        </p>
      )}

      {state.phase !== "COMPLETE" && (
        <div className="live-now" data-testid="live-now">
          {blockName(state.cursor.block_index) !== null && <p className="live-exercise">{blockName(state.cursor.block_index)}</p>}
          <div className="live-counter" data-testid="live-counter" aria-hidden="true">
            <div className="live-counter-cell">
              <span className="live-counter-num">
                {unitNumber}<span className="live-counter-total"> / {totalUnits}</span>
              </span>
              <span className="live-counter-label">{isInterval ? "Раунд" : spec?.kind === "max_reps" ? "Попытка" : "Подход"}</span>
            </div>
            {spec?.target != null && (
              <div className="live-counter-cell">
                <span className="live-counter-num">{spec.kind === "time" ? formatDuration(spec.target) : formatNumber(spec.target)}</span>
                <span className="live-counter-label">{spec.kind === "time" ? "Время" : "Повт"}</span>
              </div>
            )}
          </div>
          <p className="live-target" data-testid="engine-target">
            {isInterval ? `Раунд ${unitNumber}/${totalUnits}`
              : `${spec?.kind === "max_reps" || spec?.kind === "max_time" ? "Попытка" : "Подход"} ${unitNumber}/${totalUnits}`}
            {spec?.min_target != null ? ` · Минимум ${spec.min_target} повт. (AMRAP)`
              : spec?.kind === "max_reps" || spec?.kind === "max_time" ? " · Максимум"
                : spec?.target != null && cap !== null ? ` · Цель: ${spec.target}–${cap} повт. (потолок ${cap})`
                  : spec?.target != null ? ` · Цель: ${spec.kind === "time" ? formatDuration(spec.target) : `${spec.target} повт.`}` : ""}
          </p>
          {stopRule !== null && state.phase === "WORK" && (
            <p className="live-hint" data-testid="engine-stop-rule">
              {stopRule} повт. или меньше — подход засчитывается, и блок заканчивается.
            </p>
          )}
        </div>
      )}

      <div className={`phase-panel phase-card-${PHASE_CSS[state.phase]}`}>
        <h2 className="phase-panel-label" data-testid="engine-phase">{phaseLabel}{paused ? " · пауза" : ""}</h2>
        {remainingSeconds !== null && (
          <p className={`timer-duration-label phase-timer-${PHASE_CSS[state.phase]}`} data-testid="engine-timer">
            {formatDuration(Math.ceil(remainingSeconds))}
          </p>
        )}
        {countUp && (
          <p className="timer-duration-label phase-timer-go" data-testid="engine-stopwatch">
            {formatDuration(Math.floor((state.phase_active_ms + (state.active_since !== null ? Math.max(0, nowServer - state.active_since) : 0)) / 1000))}
          </p>
        )}
        {getReadyCue && (
          <p className="get-ready-cue" data-testid="get-ready-cue">
            Приготовься · <span data-testid="get-ready-countdown">{Math.ceil(remainingSeconds ?? 0)}</span>
          </p>
        )}
        {nextBlockIndex !== null && (
          <p className="live-plan" data-testid="engine-next-block">Дальше: {blockName(nextBlockIndex) ?? "следующее упражнение"}</p>
        )}
        {state.phase === "COMPLETE" && (
          <p className="live-done-note" data-testid="engine-complete">
            Тренировка завершена · {formatDuration(Math.floor(activeElapsedMs(state, nowServer) / 1000))} в работе
          </p>
        )}
      </div>

      {(workInput || resultInput) && !finishing && (
        <section className="live-panel live-log-panel" data-testid="log-panel" ref={logPanelRef}>
          <h3 className="live-panel-title">{resultInput && isInterval ? "Сколько повторов в раунде" : "Внести подход"}</h3>
          <form id="engine-log-form" onSubmit={submit}>
            <label className="live-field">
              <span className="live-field-label">{spec?.kind === "max_time" ? "Секунды" : "Повторений"}</span>
              <input
                className="live-field-input live-value-input" aria-label="Результат подхода" type="text" inputMode="decimal"
                enterKeyHint="done" autoComplete="off" value={value}
                onChange={(e) => setValue(sanitizeDecimalInput(e.target.value))}
              />
            </label>
            {overCap && (
              <p className="live-hint" data-testid="engine-over-cap">
                Больше {cap} не засчитывается: запишется как введено, в расчёт пойдёт {cap}.
              </p>
            )}
          </form>
        </section>
      )}

      {state.phase === "CONFIRM" && !finishing && (
        <section className="live-panel" data-testid="engine-confirm">
          <h3 className="live-panel-title">Подтвердите технику и отдых</h3>
          <p className="live-hint">«Не знаю» не считается подтверждением: тренировка сохранится, но прибавки не будет.</p>
          {checksForm}
          <Button
            className="live-primary" size="l" stretched data-testid="engine-confirm-submit" disabled={busy}
            onClick={() => void enqueue("confirm_blocks", { checks: checksPayload(confirmIndexes, answers) })}
          >
            Подтвердить и завершить
          </Button>
        </section>
      )}

      {(editPanelOpen || lastLogPanel) && (
        <section className="live-panel live-log-panel live-log-collapsed" data-testid="engine-last-set">
          {editPanelOpen && edit !== null ? (
            <form data-testid="engine-edit-form" onSubmit={(event) => {
              event.preventDefault();
              if (isCompleteDecimal(edit.value)) {
                void enqueue("correct_previous", {
                  block_index: edit.block_index, set_index: edit.set_index, round_index: edit.round_index,
                  value: Number(edit.value),
                }, () => setEdit(null));  // правка закрывается, только когда сохранена
              }
            }}>
              <label className="live-field">
                <span className="live-field-label">{`Подход ${edit.set_index + 1}`}</span>
                <input
                  className="live-field-input live-value-input" aria-label="Исправить подход" type="text" inputMode="decimal"
                  value={edit.value} onChange={(e) => setEdit({ ...edit, value: sanitizeDecimalInput(e.target.value) })}
                />
              </label>
              {state.phase !== "REST" && state.phase !== "PREP" && (
                <p className="live-hint" data-testid="engine-edit-pending">Правка ещё не сохранена.</p>
              )}
              <Button className="live-save" size="m" stretched mode="bezeled" type="submit" disabled={busy || !isCompleteDecimal(edit.value)}>
                Сохранить подход
              </Button>
              <Button
                className="live-save" size="m" stretched mode="outline" type="button" data-testid="engine-edit-cancel"
                onClick={() => setEdit(null)}
              >
                Отменить правку
              </Button>
            </form>
          ) : lastLog !== null && (
            <div className="live-summary-row">
              <p className="live-summary-line" data-testid="log-panel-summary">
                {formatLoggedSetSummary(lastLog.set_index + 1, String(lastLog.value ?? ""), logLabel(lastLog))}
              </p>
              <button
                type="button" className="live-link-button live-edit-button" data-testid="engine-edit-last"
                onClick={() => setEdit({
                  block_index: lastLog.block_index, set_index: lastLog.set_index, round_index: lastLog.round_index,
                  value: String(lastLog.value ?? ""),
                })}
              >
                Изменить
              </button>
            </div>
          )}
        </section>
      )}

      {extraOpen && extraAllowed && extraBlockIndex !== null && (
        <section className="live-panel">
          <h3 className="live-panel-title">Ещё подход</h3>
          <form data-testid="extra-set-form" onSubmit={(event) => {
            event.preventDefault();
            if (isCompleteDecimal(extraValue)) {
              void enqueue("add_extra_set", { block_index: extraBlockIndex, value: Number(extraValue) }, () => {
                setExtraValue("");
                setExtraOpen(false);
              });
            }
          }}>
            <label className="live-field">
              <span className="live-field-label">Повторений</span>
              <input
                className="live-field-input live-value-input" aria-label="Ещё подход" type="text" inputMode="decimal"
                value={extraValue} onChange={(e) => setExtraValue(sanitizeDecimalInput(e.target.value))}
              />
            </label>
            <Button className="live-save" size="l" stretched type="submit" disabled={busy || !isCompleteDecimal(extraValue)}>Записать</Button>
            <Button className="live-save" size="l" stretched mode="outline" type="button" onClick={() => setExtraOpen(false)}>Отмена</Button>
          </form>
        </section>
      )}

      {state.phase === "COMPLETE" && state.status === "completed" && !finishing && (
        <section className="live-panel" data-testid="workout-review">
          <h3 className="live-panel-title">Как прошла тренировка?</h3>
          <EffortChips value={reviewEffort} onPick={(next) => setReviewEffort(reviewEffort === next ? null : next)} />
          <label className="live-field live-note-field">
            <span className="live-field-label">Заметка</span>
            <textarea
              className="live-field-input live-note-textarea" aria-label="Заметка к тренировке" rows={3}
              maxLength={WORKOUT_COMMENT_MAX} value={reviewComment} onChange={(e) => setReviewComment(e.target.value)}
            />
          </label>
        </section>
      )}

      {finishing && (
        <div className="gap-banner live-finish-status" data-testid="finish-pending" role="status">
          <p>{online ? "Завершаю тренировку…" : "Тренировка завершена: результат сохранён на устройстве и отправится, когда появится сеть."}</p>
          <button type="button" className="live-link-button" data-testid="finish-leave" onClick={onLeave}>Выйти</button>
        </div>
      )}

      {!finishing && !reviewOpen && !extraOpen && (
        <div className="live-transport">
          {(workInput || resultInput) && (
            <Button className="live-primary" size="l" stretched type="submit" form="engine-log-form" data-testid="engine-submit" disabled={busy || !isCompleteDecimal(value)}>
              Готово
            </Button>
          )}
          {workInput && stopRule !== null && (
            <Button
              className="live-secondary" size="m" stretched mode="bezeled" data-testid="engine-submit-technique-broken"
              disabled={busy || !isCompleteDecimal(value)} onClick={() => submit(undefined, "invalid")}
            >
              Готово · техника нарушена (конец блока)
            </Button>
          )}
          {(countUp || (timedWork && spec?.kind === "time")) && (
            <Button
              className={countUp ? "live-primary" : "live-secondary"} size={countUp ? "l" : "m"} stretched mode={countUp ? undefined : "bezeled"}
              data-testid="engine-stop" disabled={busy} onClick={() => void enqueue("stop", { phase_seq: state.phase_seq })}
            >
              Стоп
            </Button>
          )}
          {state.phase === "COMPLETE" && state.status === "completed" && (
            <Button className="live-primary" size="l" stretched data-testid="engine-save" disabled={busy} onClick={() => void requestFinish()}>
              Сохранить
            </Button>
          )}
          <div className="live-secondary-row">
            {showSkip && (
              <Button
                className="live-secondary" size="m" stretched mode="bezeled" data-testid="engine-skip" disabled={busy}
                onClick={() => void enqueue("skip_wait", { phase_seq: state.phase_seq })}
              >
                Начать сейчас
              </Button>
            )}
            {state.status === "active" && state.phase !== "CONFIRM" && (
              <Button
                className="live-secondary" size="m" stretched mode="bezeled" data-testid="pause-toggle" disabled={busy}
                onClick={() => void enqueue(paused ? "resume" : "pause", { phase_seq: state.phase_seq })}
              >
                {paused ? "Продолжить" : "Пауза"}
              </Button>
            )}
            {extraAllowed && (
              <Button
                className="live-secondary" size="m" stretched mode="bezeled" data-testid="extra-set-button"
                onClick={() => setExtraOpen(true)}
              >
                + Ещё подход
              </Button>
            )}
          </div>
        </div>
      )}

      {reviewOpen && (
        <div className="live-sheet-layer">
          <div className="live-sheet-backdrop" onClick={() => setReviewOpen(false)} aria-hidden="true" />
          <section className="live-sheet" role="dialog" aria-modal="true" aria-label="Итог тренировки" data-testid="workout-review">
            <div className="live-sheet-handle" aria-hidden="true" />
            <h3 className="live-sheet-title">Как прошла тренировка?</h3>
            <p className="live-hint" data-testid="engine-finish-early-hint">{FINISH_EARLY_HINT}</p>
            {checksForm}
            <EffortChips value={reviewEffort} onPick={(next) => setReviewEffort(reviewEffort === next ? null : next)} />
            <label className="live-field live-note-field">
              <span className="live-field-label">Заметка</span>
              <textarea
                className="live-field-input live-note-textarea" aria-label="Заметка к тренировке" rows={3}
                maxLength={WORKOUT_COMMENT_MAX} value={reviewComment} onChange={(e) => setReviewComment(e.target.value)}
              />
            </label>
            {saveErrorBanner}
            <Button className="live-primary" size="l" stretched data-testid="engine-finish-confirm" disabled={busy} onClick={() => void requestFinish()}>
              Сохранить и завершить
            </Button>
            <Button className="live-secondary live-sheet-back" size="m" stretched mode="plain" onClick={() => setReviewOpen(false)}>
              Назад
            </Button>
            <button type="button" className="live-link-button" data-testid="engine-cancel" disabled={busy} onClick={() => void requestCancel()}>
              Отменить тренировку
            </button>
          </section>
        </div>
      )}
    </div>
  );
}

const ANSWER_OPTIONS: { value: CheckAnswer; label: string }[] = [
  { value: "valid", label: "Да" }, { value: "invalid", label: "Нет" }, { value: null, label: "Не знаю" },
];

/** #305 V5.6 §11: ответ по блоку — техника соблюдена / отдых в пределах: да, нет, не знаю (= не подтверждено).
 * Серверные факты не переспрашиваются: блок, остановленный «техника нарушена», и пауза в отдыхе между
 * подходами (отдых превышен) показываются как есть. */
function BlockChecks({ indexes, plan, state, answerOf, onAnswer, blockName }: {
  indexes: number[]; plan: EnginePlan; state: EngineState; answerOf: (index: number) => BlockAnswers;
  onAnswer: (index: number, key: keyof BlockAnswers, answer: CheckAnswer) => void;
  blockName: (index: number) => string | null;
}) {
  return (
    <div className="live-checks" data-testid="engine-checks">
      {indexes.map((index) => {
        const rest = plan.blocks[index].sets?.[0]?.rest_after_seconds ?? null;
        const answer = answerOf(index);
        return (
          <fieldset key={index} className="live-check-block" data-testid={`engine-checks-block-${index}`}>
            <legend className="live-field-label">{blockName(index) ?? `Блок ${index + 1}`}</legend>
            {techniqueStopped(state, index) ? (
              <p className="live-hint">Техника: нарушена (блок остановлен)</p>
            ) : (
              <AnswerChips
                label="Техника соблюдена" testId={`check-technique-${index}`} value={answer.technique}
                onPick={(next) => onAnswer(index, "technique", next)}
              />
            )}
            {restPaused(state, index) ? (
              <p className="live-hint">Отдых: превышен (была пауза во время отдыха)</p>
            ) : (
              <AnswerChips
                label={rest !== null ? `Отдых не дольше ${formatDuration(rest)}` : "Отдых в пределах"}
                testId={`check-rest-${index}`} value={answer.rest} onPick={(next) => onAnswer(index, "rest", next)}
              />
            )}
          </fieldset>
        );
      })}
    </div>
  );
}

function AnswerChips({ label, testId, value, onPick }: {
  label: string; testId: string; value: CheckAnswer; onPick: (value: CheckAnswer) => void;
}) {
  return (
    <div className="live-check-row">
      <span className="live-check-label">{label}</span>
      <div className="live-chips" data-testid={testId}>
        {ANSWER_OPTIONS.map((option) => (
          <button
            key={option.label} type="button" aria-pressed={value === option.value}
            className={value === option.value ? "live-chip live-chip-active" : "live-chip"} onClick={() => onPick(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function EffortChips({ value, onPick }: { value: string | null; onPick: (value: string) => void }) {
  return (
    <div className="live-chips" data-testid="workout-effort">
      {EFFORT_SCALE.map((option) => (
        <button
          key={option.value} type="button" aria-pressed={value === option.value}
          className={value === option.value ? "live-chip live-chip-active" : "live-chip"} onClick={() => onPick(option.value)}
        >
          <span className="effort-num">{option.value}</span>
          <span className="effort-word">{option.label}</span>
        </button>
      ))}
    </div>
  );
}
