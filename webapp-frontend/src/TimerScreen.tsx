import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { cancelTimer, fetchTimerStatus, startTimer, updateTimerPreferences, type TimerStatus } from "./api";
import { ensureAudioUnlocked, playCountdownBeep, playTimerBeep, playWarningBeep } from "./sound";

const STEP_SECONDS = 15;
const MIN_SECONDS = 15;
const MAX_SECONDS = 3600;

/** Отметки для предупредительных бипов (issue #63, п.5) — за 10 секунд до
 * конца отдыха и на последних 3/2/1 секундах, все короче и тише финального
 * бипа на 0. MIN_SECONDS=15 гарантирует, что 10-секундная отметка всегда
 * достижима при любой настроенной длительности. */
const WARNING_MARK_SECONDS = 10;
const COUNTDOWN_MARK_SECONDS = [3, 2, 1];

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
 * +/- контрол меняет `remaining` (сколько реально осталось прямо сейчас), а
 * не номинальный `duration` — иначе после того, как часть отдыха уже прошла,
 * клик по +/- прыгал бы обратно к почти полной длительности (issue #63:
 * `duration` не тикает сам по себе, оставался равен исходной длительности
 * весь отдых, поэтому "+15" от него был неотличим от рестарта с нуля).
 * Технически это всё равно POST /api/timer/start (тот же upsert, что и
 * обычный старт, start_at на сервере всегда "сейчас") — но раз само число
 * уже равно желаемому остатку, эффект для пользователя — именно "остаток
 * ±15", а не рестарт.
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
  const beepedMarksRef = useRef<Set<number>>(new Set());

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
    beepedMarksRef.current = new Set();
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
    async function startOrResume() {
      // Восстановление таймера при возврате в Mini App (issue #61) — если
      // на сервере уже идёт таймер с тем же контекстом (тип/блок/подход),
      // это тот же самый отдых, прерванный закрытием Telegram, а не новый
      // шаг: просто принимаем статус сервера, не перезапускаем отсчёт на
      // полную длительность. Иначе (другой контекст, истёк, отсутствует)
      // — как раньше, обычный старт с нуля.
      try {
        const status = await fetchTimerStatus(initDataRaw);
        if (
          status.active
          && status.timer_type === timerType
          && status.block_letter === blockLetter
          && status.set_number === (setNumber ?? null)
        ) {
          applyStatus(status);
          return;
        }
      } catch {
        // Не удалось получить статус — продолжаем обычным стартом ниже,
        // как если бы активного таймера не было.
      }
      await start(defaultDurationSeconds);
    }
    void startOrResume();
    // Проверяет восстановление ровно один раз при входе на этот экран
    // таймера — повторный старт того же экрана происходит через
    // adjust()/новый TimerScreen с новым key, не через этот эффект.
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
    const beeped = beepedMarksRef.current;
    if (beeped.has(remaining)) {
      return;
    }
    if (remaining === 0) {
      beeped.add(0);
      playTimerBeep();
    } else if (remaining === WARNING_MARK_SECONDS) {
      beeped.add(remaining);
      playWarningBeep();
    } else if (COUNTDOWN_MARK_SECONDS.includes(remaining)) {
      beeped.add(remaining);
      playCountdownBeep();
    }
  }, [remaining]);

  function adjust(deltaSeconds: number) {
    const next = Math.min(MAX_SECONDS, Math.max(MIN_SECONDS, remaining + deltaSeconds));
    if (next === remaining) {
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
