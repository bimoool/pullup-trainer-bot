/**
 * Phase C4b-1 (issue #188) — единый мм:сс helper для Workout Builder.
 * Раньше в проекте было несколько независимых форматтеров секунд
 * (formatSeconds в HistoryScreen.tsx/SessionSummaryScreen.tsx/
 * IntervalLiveScreen.tsx и т.д.) — issue #188 явно просит не плодить
 * ещё одну независимую реализацию для Builder, один helper на весь
 * модуль форм (parse + format + validation).
 */

/** Секунды -> "мм:сс", всегда двузначные секунды (00:45, 01:30, 03:00). */
export function formatSecondsAsMinutesSeconds(totalSeconds: number): string {
  const clamped = Math.max(0, Math.round(totalSeconds));
  const minutes = Math.floor(clamped / 60);
  const seconds = clamped % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

/** "мм:сс" -> секунды. Принимает "3:00"/"03:00" одинаково (минуты не
 * обязаны быть двузначными на вводе, только на отображении). null, если
 * строка не распознана как мм:сс (не бросает исключение — вызывающий код
 * сам решает, как показать ошибку валидации). */
export function parseMinutesSecondsToSeconds(display: string): number | null {
  const trimmed = display.trim();
  const match = /^(\d{1,3}):([0-5]?\d)$/.exec(trimmed);
  if (!match) {
    return null;
  }
  const minutes = Number(match[1]);
  const seconds = Number(match[2]);
  return minutes * 60 + seconds;
}

/** Валидна ли строка как мм:сс вообще (для инлайн-валидации поля до
 * привязки к конкретным бизнес-правилам вроде "> 0"). */
export function isValidMinutesSecondsInput(display: string): boolean {
  return parseMinutesSecondsToSeconds(display) !== null;
}
