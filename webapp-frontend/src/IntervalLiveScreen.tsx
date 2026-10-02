import { useEffect, useRef, useState } from "react";

import {
  completeLiveSession,
  finishLiveIntervalBlock,
  type LiveSessionCompleteResponse,
  type LiveSessionResponse,
} from "./apiV2";
import { computeClockOffsetMs, computeIntervalState, type IntervalPhase } from "./intervalTiming";
import { useBackButton } from "./useBackButton";
import { disableWakeLock, enableWakeLock } from "./wakeLock";

type Props = {
  initDataRaw: string;
  /** initialSession.interval гарантированно не null — вызывающий код
   * (PlanSessionFlow.tsx) уже проверил это перед рендером этого
   * компонента, отдельная ветка от standard SessionLiveScreen.tsx (issue
   * #215, раздел 13 — "Interval получает отдельную rendering branch",
   * не встраивается в существующую offline-очередь/ручной ввод подхода,
   * которые interval вообще не нужны). */
  initialSession: LiveSessionResponse;
  onCompleted: (result: LiveSessionCompleteResponse) => void;
  /** R1 — interval-блок в СЕРЕДИНЕ тренировки закончился: сессия осталась
   * "started" и ждёт следующий блок (interstitial). */
  onAdvanced?: (session: LiveSessionResponse) => void;
  title?: string;
};

const PHASE_LABELS: Record<IntervalPhase, string> = {
  get_ready: "Подготовка",
  work: "Работа",
  rest: "Отдых",
  done: "Готово",
};

function formatSeconds(totalSeconds: number): string {
  const clamped = Math.max(0, Math.round(totalSeconds));
  const minutes = Math.floor(clamped / 60);
  const seconds = clamped % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/**
 * Interval-режим живой тренировки (Phase B2, issue #215) — «3 минуты
 * подтягиваний»: WORK/REST переключаются автоматически по абсолютному
 * времени, без ручного Save Set и без API round-trip на каждую смену
 * фазы (раздел 11 — "Frontend НЕ вызывает backend каждые 10/20 секунд").
 *
 * Clock sync: clockOffsetMs вычисляется один раз из initialSession.server_time
 * при монтировании (раздел 7), correctedNow = Date.now() + clockOffsetMs
 * используется для ВСЕХ вычислений фазы — не сравнивается голый Date.now()
 * с серверными timestamps.
 *
 * Deadline: при достижении total_end_at делается ОДИН read/complete-call
 * (раздел 12) — completeLiveSession, тот же endpoint, что standard-путь
 * уже использует, подтверждённо идемпотентен даже после lazy finalization
 * (Phase B1 backend contract) — не создаётся собственный client-side
 * completed result.
 */
export function IntervalLiveScreen({ initDataRaw, initialSession, onCompleted, onAdvanced, title }: Props) {
  const interval = initialSession.interval;

  // issue #215/#310 — все хуки ДО любого раннего return (тот же паттерн,
  // что уже исправлен в SessionLiveScreen.tsx этой же сессией: React
  // требует одинаковый порядок хуков на каждый рендер). interval гарантированно
  // не null по контракту вызывающего кода (PlanSessionFlow.tsx), но TS
  // видит `| null` — используем безопасный дефолт ТОЛЬКО для инициализации
  // хуков, реальная проверка/ранний return — ниже, после всех хуков.
  const clockOffsetMsRef = useRef(computeClockOffsetMs(initialSession.server_time));
  const [nowMs, setNowMs] = useState(() => Date.now() + clockOffsetMsRef.current);
  const completionRequestedRef = useRef(false);
  const [completing, setCompleting] = useState(false);
  const [completeError, setCompleteError] = useState<string | null>(null);

  const blockName = initialSession.blocks[initialSession.current_block_index]?.exercise_name ?? null;
  const executionStartedAtMs = interval !== null ? new Date(interval.execution_started_at).getTime() : 0;

  // Лёгкий тик 250мс (issue #215, раздел 20) — плавный countdown, фаза
  // вычисляется заново на каждый тик из абсолютных timestamps, не
  // декрементируется как "10, 9, 8...".
  useEffect(() => {
    const timer = window.setInterval(() => {
      setNowMs(Date.now() + clockOffsetMsRef.current);
    }, 250);
    return () => window.clearInterval(timer);
  }, []);

  // Возврат из фона — пересчёт немедленно, не ждём следующего тика
  // (тот же принцип, что SessionLiveScreen.tsx уже применяет).
  useEffect(() => {
    function handleVisibilityChange() {
      if (document.visibilityState === "visible") {
        setNowMs(Date.now() + clockOffsetMsRef.current);
      }
    }
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => document.removeEventListener("visibilitychange", handleVisibilityChange);
  }, []);

  useEffect(() => {
    enableWakeLock();
    return () => disableWakeLock();
  }, []);

  const state = computeIntervalState({
    executionStartedAtMs, nowMs,
    totalDurationSeconds: interval?.total_duration_seconds ?? 0,
    workSeconds: interval?.work_seconds ?? 0, restSeconds: interval?.rest_seconds ?? 0,
  });

  // Deadline (issue #215, раздел 12) — один complete-call, не client-side
  // результат. completionRequestedRef защищает от повторного вызова на
  // каждый последующий 250мс-тик после того, как phase уже "done".
  useEffect(() => {
    if (interval === null || state.phase !== "done" || completionRequestedRef.current) {
      return;
    }
    completionRequestedRef.current = true;
    setCompleting(true);
    // Дедлайн ЭТОГО блока: сервер сам решает — продвинуть сессию к
    // следующему блоку (середина) или завершить её (последний блок).
    finishLiveIntervalBlock(initDataRaw, initialSession.id, initialSession.current_block_index)
      .then((result) => {
        if (result.status === "completed") {
          onCompleted(result);
        } else {
          onAdvanced?.(result);
        }
      })
      .catch((error) => {
        setCompleteError(error instanceof Error ? error.message : String(error));
        setCompleting(false);
        completionRequestedRef.current = false; // разрешить повторную попытку
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.phase]);

  useBackButton(() => {
    if (window.confirm("Закончить тренировку раньше времени? Прогресс будет зачтён по факту.")) {
      if (!completionRequestedRef.current) {
        completionRequestedRef.current = true;
        setCompleting(true);
        void completeLiveSession(initDataRaw, initialSession.id, true).then(onCompleted);
      }
    }
  }, [initialSession.id]);

  if (interval === null) {
    // Недостижимо при корректном вызове (PlanSessionFlow проверяет перед
    // рендером), но типобезопасность требует ветку.
    return <p className="screen-message">Ошибка: interval-состояние отсутствует.</p>;
  }

  return (
    <div className="live-screen" data-phase={state.phase === "get_ready" ? "get_ready" : state.phase === "work" ? "go" : "rest"}>
      <header className="live-header">
        <div className="live-header-text">
          <p className="live-eyebrow">Живая тренировка</p>
          {title && <p className="live-workout-title">{title}</p>}
          {blockName && <p className="live-plan">{blockName} · Интервалы</p>}
        </div>
      </header>
      {completeError && (
        <p className="gap-banner">Не удалось завершить: {completeError}. Пробую снова…</p>
      )}

      {state.phase === "get_ready" ? (
        <div className="phase-panel phase-card-get_ready">
          <h2 className="phase-panel-label">{PHASE_LABELS.get_ready}</h2>
          <p className="timer-duration-label phase-timer-get_ready">
            {Math.max(0, Math.ceil(state.remainingInPhaseSeconds))}
          </p>
        </div>
      ) : (
        // WORK визуально = "go" (зелёный, активная фаза), REST = "rest"
        // (синий) — переиспользованы уже существующие, стилизованные
        // классы SessionLiveScreen.tsx (.phase-card-go/.phase-card-rest,
        // index.css/live.css), не изобретены новые unstyled interval-phase-*.
        <div className={`phase-panel phase-card-${state.phase === "work" ? "go" : "rest"}`}>
          <h2 className="phase-panel-label">{PHASE_LABELS[state.phase]}</h2>
          <p className={`timer-duration-label phase-timer-${state.phase === "work" ? "go" : "rest"}`}>
            {formatSeconds(state.remainingInPhaseSeconds)}
          </p>
          <p className="live-done-note">Осталось: {formatSeconds(state.remainingTotalSeconds)}</p>
        </div>
      )}

      {completing && <p className="screen-message">Завершаю тренировку…</p>}
    </div>
  );
}
