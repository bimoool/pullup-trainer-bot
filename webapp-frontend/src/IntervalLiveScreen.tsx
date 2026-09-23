import { Section } from "@telegram-apps/telegram-ui";
import { useEffect, useRef, useState } from "react";

import { completeLiveSession, type LiveSessionCompleteResponse, type LiveSessionResponse } from "./apiV2";
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
export function IntervalLiveScreen({ initDataRaw, initialSession, onCompleted, title }: Props) {
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
    completeLiveSession(initDataRaw, initialSession.id, false)
      .then((result) => {
        onCompleted(result);
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
    <div>
      <p className="plan-title">Живая тренировка</p>
      {title && <p className="block-subtitle">{title}</p>}
      {completeError && (
        <p className="gap-banner">Не удалось завершить: {completeError}. Пробую снова…</p>
      )}

      {state.phase === "get_ready" ? (
        <Section className="block-section phase-card-get_ready" header={PHASE_LABELS.get_ready}>
          <p className="timer-duration-label phase-timer-get_ready">
            {Math.max(0, Math.ceil(state.remainingInPhaseSeconds))}
          </p>
        </Section>
      ) : (
        // WORK визуально = "go" (зелёный, активная фаза), REST = "rest"
        // (синий) — переиспользованы уже существующие, стилизованные
        // классы SessionLiveScreen.tsx (.phase-card-go/.phase-card-rest,
        // index.css), не изобретены новые unstyled interval-phase-*.
        <Section
          className={`block-section phase-card-${state.phase === "work" ? "go" : "rest"}`}
          header={PHASE_LABELS[state.phase]}
        >
          <p className={`timer-duration-label phase-timer-${state.phase === "work" ? "go" : "rest"}`}>
            {formatSeconds(state.remainingInPhaseSeconds)}
          </p>
          <p className="block-subtitle">Осталось: {formatSeconds(state.remainingTotalSeconds)}</p>
        </Section>
      )}

      {completing && <p className="screen-message">Завершаю тренировку…</p>}
    </div>
  );
}
