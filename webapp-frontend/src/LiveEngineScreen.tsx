import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useRef, useState } from "react";

import {
  completeLiveSession, fetchActiveLiveSession, postLiveEngineEvents,
  type LiveSessionCompleteResponse, type LiveSessionResponse,
} from "./apiV2";
import { formatDuration, formatLoggedSetSummary, formatNumber } from "./blockFormat";
import { isCompleteDecimal, sanitizeDecimalInput } from "./decimalInput";
import { EFFORT_SCALE, WORKOUT_COMMENT_MAX } from "./effortScale";
import { classifySyncError, type SyncFailure } from "./liveFinish";
import { activeElapsedMs, remainingMs, type EngineState, type Phase, type PlanBlock } from "./liveEngine";
import {
  clearQueue, displayState, dropAcknowledged, emptyQueue, loadQueue, newEvent, saveQueue, serverOffsetMs,
  type EngineQueue,
} from "./liveEngineClient";
import { cancelScheduledPhaseEndSound, phaseEndCueDelaySeconds, schedulePhaseEndSound } from "./phaseAudio";
import { useBackButton } from "./useBackButton";
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
const PHASE_CSS: Record<Phase, string> = { PREP: "get_ready", WORK: "go", RESULT: "go", REST: "rest", COMPLETE: "done" };

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
  const [editOpen, setEditOpen] = useState(false);
  const [editValue, setEditValue] = useState("");
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewEffort, setReviewEffort] = useState<string | null>(null);
  const [reviewComment, setReviewComment] = useState("");
  const syncing = useRef<Promise<void> | null>(null);
  const resync = useRef(false);
  const firstCompletion = useRef<LiveSessionCompleteResponse | null>(null);
  const closed = useRef(false);

  const engine = server.engine;
  const plan = engine?.plan ?? null;
  const nowServer = now + offset;
  const state: EngineState | null = plan && engine ? displayState(plan, engine.state, queue.events, nowServer) : null;

  function setQueue(next: EngineQueue) {
    queueRef.current = next;
    setQueueState(next);
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
    await clearQueue(initialSession.id);
    if (result.progression_skipped_reason === "cancelled" || result.engine_status === "cancelled") {
      onLeave();
      return;
    }
    const first = firstCompletion.current;
    onCompleted(first !== null && first.progression_result !== null
      ? { ...result, progression_result: first.progression_result, progression_skipped_reason: first.progression_skipped_reason }
      : result);
  }

  function sync(): Promise<void> {
    if (syncing.current !== null) {
      resync.current = true;
      return syncing.current;
    }
    const run = runSync().finally(() => {
      syncing.current = null;
      if (resync.current && !closed.current) {
        resync.current = false;
        void sync();
      }
    });
    syncing.current = run;
    return run;
  }

  async function runSync(): Promise<void> {
    do {
      resync.current = false;
      if (closed.current || !navigator.onLine) {
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
          acceptServer(response, started, Date.now());
          if (response.status === "completed" && firstCompletion.current === null) {
            firstCompletion.current = response;
          }
          const rest = dropAcknowledged(queueRef.current, response.event_results.map((r) => r.client_event_id));
          setQueue(rest);
          await saveQueue(rest);
          if (response.engine_status === "cancelled") {
            await finishWith(response);
            return;
          }
        }
        if (queueRef.current.complete !== null && queueRef.current.events.length === 0) {
          const review = queueRef.current.complete;
          const result = await completeLiveSession(initDataRaw, pending.sessionId, false, review);
          await finishWith(result);
          return;
        }
        setFailure(null);
      } catch (error) {
        setFailure(classifySyncError(error));
        return;
      }
    } while (resync.current);
  }

  /** Сверка с сервером: свежая проекция (дедлайны, истёкшие в фоне, уже применены сервером). */
  async function refresh(): Promise<void> {
    if (!navigator.onLine || closed.current || queueRef.current.events.length > 0) {
      return;
    }
    try {
      const started = Date.now();
      const active = await fetchActiveLiveSession(initDataRaw);
      if (active !== null && active.id === initialSession.id) {
        acceptServer(active, started, Date.now());
        return;
      }
      // Не активна на сервере: завершилась сама (проекция в фоне), на другом устройстве или отменена.
      // Идемпотентный complete отдаёт итог, ничего не повторяя (#307 T).
      const result = await completeLiveSession(initDataRaw, initialSession.id, false);
      if (result.engine_status === "cancelled" || result.progression_skipped_reason === "cancelled") {
        await finishWith(result);
        return;
      }
      if (firstCompletion.current === null) {
        firstCompletion.current = result;
      }
      setServer(result);
    } catch (error) {
      setFailure(classifySyncError(error));
    }
  }

  useEffect(() => {
    let cancelled = false;
    void loadQueue(initialSession.id).then((stored) => {
      if (cancelled) {
        return;
      }
      setQueue(stored);
      setReady(true);
      if (stored.events.length > 0 || stored.complete !== null) {
        void sync();
      } else {
        void refresh();
      }
    });
    return () => {
      cancelled = true;
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
    setEditOpen(false);
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

  async function enqueue(type: string, payload: Record<string, unknown>): Promise<void> {
    const event = newEvent(type, payload, Date.now() + offset);
    const next = { ...queueRef.current, events: [...queueRef.current.events, event] };
    setQueue(next);
    setNow(Date.now());
    await saveQueue(next);
    void sync();
  }

  async function requestFinish(): Promise<void> {
    if (state === null) {
      return;
    }
    const review = { effort: reviewEffort, comment: reviewComment.trim() || null };
    const events = state.status === "active"
      ? [...queueRef.current.events, newEvent("finish_early", {}, Date.now() + offset)]
      : queueRef.current.events;
    const next = { ...queueRef.current, events, complete: review };
    setQueue(next);
    setReviewOpen(false);
    await saveQueue(next);
    void sync();
  }

  async function requestCancel(): Promise<void> {
    if (!window.confirm("Отменить тренировку? Ничего не сохранится.")) {
      return;
    }
    setReviewOpen(false);
    await enqueue("cancel", {});
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
  const lastLogKind = lastLog !== null ? plan.blocks[lastLog.block_index]?.sets?.[lastLog.set_index]?.kind : undefined;
  const lastLogLabel = lastLogKind === "time" || lastLogKind === "max_time" ? "Секунды" : "Повторений";
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
  const phaseLabel = state.phase === "PREP" ? "Приготовься"
    : state.phase === "WORK" ? "Пошёл"
      : state.phase === "RESULT" ? (isInterval ? "Повторы раунда" : "Результат")
        : state.phase === "REST" ? "Отдых" : "Готово";
  const remainingSeconds = remaining !== null ? remaining / 1000 : null;
  const getReadyCue = state.phase === "REST" && remainingSeconds !== null && !paused && remainingSeconds <= GET_READY_CUE_SECONDS;

  const submit = (event?: React.FormEvent) => {
    event?.preventDefault();
    if (!isCompleteDecimal(value)) {
      return;
    }
    void enqueue("submit_result", {
      block_index: state.cursor.block_index, set_index: state.cursor.set_index, round_index: state.cursor.round_index,
      value: Number(value),
    });
  };

  return (
    <div className="live-screen" data-phase={PHASE_CSS[state.phase]} data-engine-phase={state.phase} data-paused={paused ? "true" : undefined}>
      <header className="live-header">
        <div className="live-header-text">
          <p className="live-eyebrow">Живая тренировка</p>
          {title && <p className="live-workout-title">{title}</p>}
        </div>
        {state.status === "active" && !finishing && (
          <button type="button" className="live-finish" data-testid="engine-finish" onClick={() => setReviewOpen(true)}>
            Завершить
          </button>
        )}
      </header>
      {!online && <p className="gap-banner">Нет сети — действия сохраняются на устройстве и уйдут при подключении.</p>}
      {online && pendingCount > 0 && <p className="gap-banner" data-testid="engine-pending">Не синхронизировано: {pendingCount}. Досылаю…</p>}
      {failure && (
        <p className="gap-banner" data-testid="engine-sync-error">
          Не удалось синхронизировать: {failure.message}.{" "}
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
            {spec?.kind === "max_reps" || spec?.kind === "max_time" ? " · Максимум"
              : spec?.target != null ? ` · Цель: ${spec.kind === "time" ? formatDuration(spec.target) : `${spec.target} повт.`}` : ""}
          </p>
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
        <section className="live-panel live-log-panel" data-testid="log-panel">
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
          </form>
        </section>
      )}

      {lastLog !== null && state.phase !== "COMPLETE" && !finishing && (state.phase === "REST" || state.phase === "PREP") && (
        <section className="live-panel live-log-panel live-log-collapsed" data-testid="engine-last-set">
          {editOpen ? (
            <form onSubmit={(event) => {
              event.preventDefault();
              if (isCompleteDecimal(editValue)) {
                void enqueue("correct_previous", {
                  block_index: lastLog.block_index, set_index: lastLog.set_index, round_index: lastLog.round_index,
                  value: Number(editValue),
                });
                setEditOpen(false);
              }
            }}>
              <label className="live-field">
                <span className="live-field-label">{`Подход ${lastLog.set_index + 1}`}</span>
                <input
                  className="live-field-input live-value-input" aria-label="Исправить подход" type="text" inputMode="decimal"
                  value={editValue} onChange={(e) => setEditValue(sanitizeDecimalInput(e.target.value))}
                />
              </label>
              <Button className="live-save" size="m" stretched mode="bezeled" type="submit" disabled={!isCompleteDecimal(editValue)}>
                Сохранить подход
              </Button>
            </form>
          ) : (
            <div className="live-summary-row">
              <p className="live-summary-line" data-testid="log-panel-summary">
                {formatLoggedSetSummary(lastLog.set_index + 1, String(lastLog.value ?? ""), lastLogLabel)}
              </p>
              <button
                type="button" className="live-link-button live-edit-button" data-testid="engine-edit-last"
                onClick={() => { setEditValue(String(lastLog.value ?? "")); setEditOpen(true); }}
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
              void enqueue("add_extra_set", { block_index: extraBlockIndex, value: Number(extraValue) });
              setExtraValue("");
              setExtraOpen(false);
            }
          }}>
            <label className="live-field">
              <span className="live-field-label">Повторений</span>
              <input
                className="live-field-input live-value-input" aria-label="Ещё подход" type="text" inputMode="decimal"
                value={extraValue} onChange={(e) => setExtraValue(sanitizeDecimalInput(e.target.value))}
              />
            </label>
            <Button className="live-save" size="l" stretched type="submit" disabled={!isCompleteDecimal(extraValue)}>Записать</Button>
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
            <Button className="live-primary" size="l" stretched type="submit" form="engine-log-form" data-testid="engine-submit" disabled={!isCompleteDecimal(value)}>
              Готово
            </Button>
          )}
          {(countUp || (timedWork && spec?.kind === "time")) && (
            <Button
              className={countUp ? "live-primary" : "live-secondary"} size={countUp ? "l" : "m"} stretched mode={countUp ? undefined : "bezeled"}
              data-testid="engine-stop" onClick={() => void enqueue("stop", { phase_seq: state.phase_seq })}
            >
              Стоп
            </Button>
          )}
          {state.phase === "COMPLETE" && state.status === "completed" && (
            <Button className="live-primary" size="l" stretched data-testid="engine-save" onClick={() => void requestFinish()}>
              Сохранить
            </Button>
          )}
          <div className="live-secondary-row">
            {showSkip && (
              <Button
                className="live-secondary" size="m" stretched mode="bezeled" data-testid="engine-skip"
                onClick={() => void enqueue("skip_wait", { phase_seq: state.phase_seq })}
              >
                Начать сейчас
              </Button>
            )}
            {state.status === "active" && (
              <Button
                className="live-secondary" size="m" stretched mode="bezeled" data-testid="pause-toggle"
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
            <p className="live-hint">Что сделано — зачтено, остальное останется в плане.</p>
            <EffortChips value={reviewEffort} onPick={(next) => setReviewEffort(reviewEffort === next ? null : next)} />
            <label className="live-field live-note-field">
              <span className="live-field-label">Заметка</span>
              <textarea
                className="live-field-input live-note-textarea" aria-label="Заметка к тренировке" rows={3}
                maxLength={WORKOUT_COMMENT_MAX} value={reviewComment} onChange={(e) => setReviewComment(e.target.value)}
              />
            </label>
            <Button className="live-primary" size="l" stretched data-testid="engine-finish-confirm" onClick={() => void requestFinish()}>
              Сохранить и завершить
            </Button>
            <Button className="live-secondary live-sheet-back" size="m" stretched mode="plain" onClick={() => setReviewOpen(false)}>
              Назад
            </Button>
            <button type="button" className="live-link-button" data-testid="engine-cancel" onClick={() => void requestCancel()}>
              Отменить тренировку
            </button>
          </section>
        </div>
      )}
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
