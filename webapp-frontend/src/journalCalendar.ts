// Чистые помощники календаря Журнала (#256): месяцы "YYYY-MM", даты "YYYY-MM-DD",
// сетка Пн-первой, группировка "неделя → день". Без DOM и без обращения к часовому
// поясу браузера: день любого момента считается в часовом поясе пользователя.

export const DEFAULT_JOURNAL_TZ = "Europe/Moscow";

const MONTH_NAMES = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];
const MONTH_GENITIVE = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];
const WEEKDAY_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

export const WEEKDAY_HEADERS = WEEKDAY_SHORT;

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

function parseMonth(month: string): { year: number; month: number } {
  const [year, number] = month.split("-").map(Number);
  return { year, month: number };
}

function parseDate(date: string): { year: number; month: number; day: number } {
  const [year, month, day] = date.split("-").map(Number);
  return { year, month, day };
}

export function monthKey(year: number, month: number): string {
  return `${year}-${pad(month)}`;
}

/** Сдвиг месяца "YYYY-MM" на delta месяцев (через границу года). */
export function shiftMonth(month: string, delta: number): string {
  const { year, month: number } = parseMonth(month);
  const index = year * 12 + (number - 1) + delta;
  return monthKey(Math.floor(index / 12), (index % 12 + 12) % 12 + 1);
}

/** "2026-10" -> "Октябрь 2026". */
export function monthLabel(month: string): string {
  const { year, month: number } = parseMonth(month);
  return `${MONTH_NAMES[number - 1]} ${year}`;
}

export function daysInMonth(month: string): number {
  const { year, month: number } = parseMonth(month);
  return new Date(Date.UTC(year, number, 0)).getUTCDate();
}

/** Первый и последний день месяца (включительно) — диапазон для бэкенда. */
export function monthRange(month: string): { from: string; to: string } {
  return { from: `${month}-01`, to: `${month}-${pad(daysInMonth(month))}` };
}

/** Календарная дата момента в заданном часовом поясе: "YYYY-MM-DD". */
export function localDateKey(isoDateTime: string, timeZone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone, year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date(isoDateTime));
  const pick = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${pick("year")}-${pick("month")}-${pick("day")}`;
}

/** Текущий месяц "YYYY-MM" в часовом поясе. */
export function currentMonthIn(timeZone: string, now: Date = new Date()): string {
  return localDateKey(now.toISOString(), timeZone).slice(0, 7);
}

/** Индекс дня недели, Пн = 0 … Вс = 6. */
function weekdayIndex(date: string): number {
  const { year, month, day } = parseDate(date);
  return (new Date(Date.UTC(year, month - 1, day)).getUTCDay() + 6) % 7;
}

function addDays(date: string, delta: number): string {
  const { year, month, day } = parseDate(date);
  const moved = new Date(Date.UTC(year, month - 1, day + delta));
  return `${moved.getUTCFullYear()}-${pad(moved.getUTCMonth() + 1)}-${pad(moved.getUTCDate())}`;
}

/** Понедельник недели, в которую попадает дата. */
export function weekStartOf(date: string): string {
  return addDays(date, -weekdayIndex(date));
}

/** Сетка месяца: недели по 7 ячеек, Пн-первая; пустые ячейки — null. */
export function buildMonthGrid(month: string): (string | null)[][] {
  const total = daysInMonth(month);
  const cells: (string | null)[] = Array.from({ length: weekdayIndex(`${month}-01`) }, () => null);
  for (let day = 1; day <= total; day += 1) {
    cells.push(`${month}-${pad(day)}`);
  }
  while (cells.length % 7 !== 0) {
    cells.push(null);
  }
  const weeks: (string | null)[][] = [];
  for (let index = 0; index < cells.length; index += 7) {
    weeks.push(cells.slice(index, index + 7));
  }
  return weeks;
}

/** "2026-10-01" -> "Чт, 1 октября". */
export function dayLabel(date: string): string {
  const { month, day } = parseDate(date);
  return `${WEEKDAY_SHORT[weekdayIndex(date)]}, ${day} ${MONTH_GENITIVE[month - 1]}`;
}

/** Подпись недели по её понедельнику: "28 сент. – 4 окт." / "5–11 окт.". */
export function weekLabel(weekStart: string): string {
  const start = parseDate(weekStart);
  const end = parseDate(addDays(weekStart, 6));
  const short = (month: number) => MONTH_GENITIVE[month - 1].slice(0, 3);
  if (start.month === end.month) {
    return `${start.day}–${end.day} ${short(end.month)}.`;
  }
  return `${start.day} ${short(start.month)}. – ${end.day} ${short(end.month)}.`;
}

export interface JournalWeekGroup<T> {
  weekStart: string;
  days: { date: string; items: T[] }[];
}

/** Группировка "неделя (Пн–Вс) → день"; новые недели/дни первыми, порядок
 * элементов внутри дня сохраняется как во входе. */
export function groupByWeekAndDay<T>(entries: { date: string; item: T }[]): JournalWeekGroup<T>[] {
  const byDay = new Map<string, T[]>();
  for (const { date, item } of entries) {
    byDay.set(date, [...(byDay.get(date) ?? []), item]);
  }
  const dates = [...byDay.keys()].sort().reverse();
  const weeks: JournalWeekGroup<T>[] = [];
  for (const date of dates) {
    const start = weekStartOf(date);
    let week = weeks.find((candidate) => candidate.weekStart === start);
    if (week === undefined) {
      week = { weekStart: start, days: [] };
      weeks.push(week);
    }
    week.days.push({ date, items: byDay.get(date) ?? [] });
  }
  return weeks;
}
