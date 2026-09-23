/**
 * Клиентский порт app/domain/interval_timing.py (Phase B1/B2, issue #215) —
 * та же формула, что сервер уже применяет для расчёта фазы. Frontend не
 * делает round-trip на каждую смену WORK/REST (10/20 сек) — вычисляет
 * следующую фазу локально по тем же входным данным, что сервер вернул при
 * Start/Active: execution_started_at, protocol, скорректированное "сейчас".
 * Один источник формулы концептуально (server-authoritative timing
 * anchor), два независимых вычисления одного и того же детерминированного
 * расписания — не два источника правды: оба должны дать один результат по
 * построению, backend остаётся авторитетным на re-fetch (Start/reload/
 * completion).
 */

export type IntervalPhase = "get_ready" | "work" | "rest" | "done";

export type ComputedIntervalState = {
  phase: IntervalPhase;
  /** Абсолютный конец текущей фазы, мс с эпохи. null только для "done"
   * (симметрично backend-контракту — см. IntervalStateResponse). */
  phaseEndsAtMs: number | null;
  totalEndAtMs: number;
  /** Секунд до конца текущей фазы, >= 0, уже не может быть отрицательным
   * (если "сейчас" ушло за totalEndAtMs — phase уже "done"). */
  remainingInPhaseSeconds: number;
  /** Секунд до конца всей тренировки, >= 0. */
  remainingTotalSeconds: number;
  completedCycles: number;
};

/** Клиентский порт app.domain.interval_timing.calculate_completed_cycles —
 * те же 5 контрольных случаев, что backend-тест уже проверяет (180/10/20
 * -> 6, 15/10/20 -> 1, 5/10/20 -> 0, 30/10/20 -> 1, 40/10/20 -> 2). */
export function calculateCompletedCycles(
  elapsedSeconds: number, totalDurationSeconds: number, workSeconds: number, restSeconds: number,
): number {
  const elapsedCapped = Math.min(elapsedSeconds, totalDurationSeconds);
  if (elapsedCapped < workSeconds) {
    return 0;
  }
  const cycleDuration = workSeconds + restSeconds;
  return Math.floor((elapsedCapped - workSeconds) / cycleDuration) + 1;
}

export function computeIntervalState(params: {
  executionStartedAtMs: number;
  nowMs: number;
  totalDurationSeconds: number;
  workSeconds: number;
  restSeconds: number;
}): ComputedIntervalState {
  const { executionStartedAtMs, nowMs, totalDurationSeconds, workSeconds, restSeconds } = params;
  const totalEndAtMs = executionStartedAtMs + totalDurationSeconds * 1000;
  const completedCycles = calculateCompletedCycles(
    Math.max(0, (nowMs - executionStartedAtMs) / 1000), totalDurationSeconds, workSeconds, restSeconds,
  );

  if (nowMs < executionStartedAtMs) {
    return {
      phase: "get_ready",
      phaseEndsAtMs: executionStartedAtMs,
      totalEndAtMs,
      remainingInPhaseSeconds: (executionStartedAtMs - nowMs) / 1000,
      remainingTotalSeconds: (totalEndAtMs - nowMs) / 1000,
      completedCycles,
    };
  }

  if (nowMs >= totalEndAtMs) {
    return {
      phase: "done", phaseEndsAtMs: null, totalEndAtMs,
      remainingInPhaseSeconds: 0, remainingTotalSeconds: 0, completedCycles,
    };
  }

  const elapsedMs = nowMs - executionStartedAtMs;
  const cycleDurationMs = (workSeconds + restSeconds) * 1000;
  const positionMs = elapsedMs % cycleDurationMs;
  const cycleStartMs = nowMs - positionMs;

  if (positionMs < workSeconds * 1000) {
    const phaseEndsAtMs = Math.min(cycleStartMs + workSeconds * 1000, totalEndAtMs);
    return {
      phase: "work", phaseEndsAtMs, totalEndAtMs,
      remainingInPhaseSeconds: (phaseEndsAtMs - nowMs) / 1000,
      remainingTotalSeconds: (totalEndAtMs - nowMs) / 1000,
      completedCycles,
    };
  }

  const phaseEndsAtMs = Math.min(cycleStartMs + cycleDurationMs, totalEndAtMs);
  return {
    phase: "rest", phaseEndsAtMs, totalEndAtMs,
    remainingInPhaseSeconds: (phaseEndsAtMs - nowMs) / 1000,
    remainingTotalSeconds: (totalEndAtMs - nowMs) / 1000,
    completedCycles,
  };
}

/** clockOffsetMs = parse(server_time) - Date.now(), пересчитывается на
 * каждый backend-ответ (issue #215, раздел 7) — не отдельный /time
 * эндпоинт, просто поле уже существующего LiveSessionResponse. */
export function computeClockOffsetMs(serverTimeIso: string): number {
  return new Date(serverTimeIso).getTime() - Date.now();
}
