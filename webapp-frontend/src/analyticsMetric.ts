// Чистые помощники метрики «Тренировки / Минуты» (CRIMPD #259): диапазоны дат,
// валидация «Свой», формат минут. Без React и без текущего времени — "сегодня"
// (локальная дата в поясе пользователя) приходит снаружи.

export type MetricKey = "workouts" | "minutes";
export type RangeKey = "1m" | "3m" | "custom";

export interface DateRange {
  from: string;
  to: string;
}

/** Согласовано с бэкендом (MAX_RANGE_DAYS = 366). */
export const MAX_RANGE_DAYS = 366;

const DAY_MS = 86_400_000;

function parseIso(iso: string): number {
  const [year, month, day] = iso.split("-").map(Number);
  return Date.UTC(year, month - 1, day);
}

function toIso(ms: number): string {
  const date = new Date(ms);
  const y = String(date.getUTCFullYear()).padStart(4, "0");
  return `${y}-${String(date.getUTCMonth() + 1).padStart(2, "0")}-${String(date.getUTCDate()).padStart(2, "0")}`;
}

export function shiftIsoDate(iso: string, days: number): string {
  return toIso(parseIso(iso) + days * DAY_MS);
}

/** Локальная календарная дата момента в часовом поясе (YYYY-MM-DD). */
export function localIsoDate(now: Date, timeZone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" })
    .formatToParts(now);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")}`;
}

/** 1 мес = последние 30 дней, 3 мес = последние 90 дней, включая сегодня. */
export function presetRange(preset: "1m" | "3m", today: string): DateRange {
  return { from: shiftIsoDate(today, preset === "1m" ? -29 : -89), to: today };
}

/** null — диапазон допустим; иначе короткое сообщение для UI. */
export function validateCustomRange(from: string, to: string): string | null {
  if (!from || !to) {
    return "Укажите обе даты";
  }
  if (from > to) {
    return "Начало позже конца";
  }
  if ((parseIso(to) - parseIso(from)) / DAY_MS >= MAX_RANGE_DAYS) {
    return "Не больше года";
  }
  return null;
}

/** "2026-09-28" -> "28.09" */
export function formatWeekLabel(isoDate: string): string {
  const [, month, day] = isoDate.split("-");
  return `${day}.${month}`;
}

/** Минуты для подписей: 45 -> "45 мин", 135 -> "2 ч 15 мин", 120 -> "2 ч". */
export function formatMinutes(minutes: number): string {
  if (minutes < 60) {
    return `${minutes} мин`;
  }
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} ч` : `${hours} ч ${rest} мин`;
}
