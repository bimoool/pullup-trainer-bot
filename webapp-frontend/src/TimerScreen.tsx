import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { cancelTimer, fetchTimerStatus, startTimer, updateTimerPreferences, type TimerStatus } from "./api";
import { ensureAudioUnlocked, playTimerBeep } from "./sound";

const STEP_SECONDS = 15;
const MIN_SECONDS = 15;
const MAX_SECONDS = 3600;

type Props = {
  initDataRaw: string;
  timerType: "rest_between_sets" | "big_break";
  blockLetter: "A" | "B" | null;
  setNumber?: number | null;
  title: string;
  defaultDurationSeconds: number;
  onDone: () => void;
  children?: ReactNode;
};

function formatMmSs(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/**
 * Персистентный таймер (issue #59, волна 1/2) — источник правды всегда
 * сервер: старт пишет started_at на бэкенде, локальный setInterval ниже
 * только тикает визуально между опросами GET /api/timer/status, которые
 * происходят на возврате в приложение (focus/visibilitychange), не только
 * один раз при монтировании.
 *
 * +/- контрол меняет длительность и до, и после старта — оба случая просто
 * заново вызывают POST /api/timer/start (тот же upsert, что и обычный
 * старт), это одновременно и меняет число, и перезапускает отсчёт с этой
 * длительности (согласовано в issue: "пересчитать duration_seconds тем же
 * POST /api/timer/start, раз это upsert").
 */
export function TimerScreen({
  initDataRaw,
  timerType,
  blockLetter,
  setNumber,
  title,
  defaultDurationSeconds,
  onDone,
  children,
}: Props) {
  const [duration, setDuration] = useState(defaultDurationSeconds);
  const [remaining, setRemaining] = useState(defaultDurationSeconds);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const beepedRef = useRef(false);

  function applyStatus(status: TimerStatus) {
    if (status.duration_seconds !== null) {
      setDuration(status.duration_seconds);
    }
    if (status.remaining_seconds !== null) {
      setRemaining(status.remaining_seconds);
    }
  }

  async function start(nextDuration: number) {
    ensureAudioUnlocked();
    beepedRef.current = false;
    try {
      const status = await startTimer(initDataRaw, {
        timer_type: timerType,
        duration_seconds: nextDuration,
        block_letter: blockLetter,
        set_number: setNumber ?? null,
      });
      applyStatus(status);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    void start(defaultDurationSeconds);
    // Стартует ровно один раз при входе на этот экран таймера — повторный
    // старт того же экрана происходит через adjust()/новый TimerScreen с
    // новым key, не через этот эффект.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    async function resync() {
      try {
        const status = await fetchTimerStatus(initDataRaw);
        applyStatus(status);
      } catch {
        // Сеть недоступна в момент пересинхронизации — локальный тик
        // продолжает идти, следующий фокус/интервал повторит попытку.
      }
    }
    function onVisible() {
      if (document.visibilityState === "visible") {
        void resync();
      }
    }
    window.addEventListener("focus", resync);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.removeEventListener("focus", resync);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [initDataRaw]);

  useEffect(() => {
    const interval = setInterval(() => {
      setRemaining((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (remaining === 0 && !beepedRef.current) {
      beepedRef.current = true;
      playTimerBeep();
    }
  }, [remaining]);

  function adjust(deltaSeconds: number) {
    const next = Math.min(MAX_SECONDS, Math.max(MIN_SECONDS, duration + deltaSeconds));
    if (next === duration) {
      return;
    }
    setSaved(false);
    void start(next);
  }

  async function handleRemember() {
    ensureAudioUnlocked();
    try {
      await updateTimerPreferences(initDataRaw, {
        block_letter: timerType === "rest_between_sets" ? blockLetter : null,
        duration_seconds: duration,
      });
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleSkip() {
    ensureAudioUnlocked();
    try {
      await cancelTimer(initDataRaw);
    } catch {
      // Отмена — лучшее усилие, не блокирует переход к следующему шагу.
    }
    onDone();
  }

  function handleContinue() {
    ensureAudioUnlocked();
    onDone();
  }

  const isFinished = remaining <= 0;

  return (
    <div className="timer-card">
      <p className="plan-title">{title}</p>
      <p className={isFinished ? "timer-display timer-display-done" : "timer-display"}>{formatMmSs(remaining)}</p>

      <div className="timer-adjust-row">
        <Button mode="outline" size="s" onClick={() => adjust(-STEP_SECONDS)}>
          −{STEP_SECONDS} сек
        </Button>
        <span className="timer-duration-label">{formatMmSs(duration)}</span>
        <Button mode="outline" size="s" onClick={() => adjust(STEP_SECONDS)}>
          +{STEP_SECONDS} сек
        </Button>
      </div>

      <Button mode="outline" size="s" disabled={saved} onClick={() => void handleRemember()}>
        {saved ? "Сохранено как значение по умолчанию" : "Запомнить как значение по умолчанию"}
      </Button>

      {children}

      {error && <p className="error-banner">{error}</p>}

      <Button className="action-button" size="l" stretched disabled={!isFinished} onClick={handleContinue}>
        {isFinished ? "Продолжить" : "Ждём окончания отдыха…"}
      </Button>
      <Button className="action-button" size="l" stretched mode="outline" onClick={() => void handleSkip()}>
        Пропустить
      </Button>
    </div>
  );
}
