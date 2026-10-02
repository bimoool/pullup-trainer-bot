// Чистые помощники экрана «Вес/Рост» (#270): даты замеров и точки SVG-тренда. Без React/DOM.

export interface TrendEntry {
  value: string;
  measured_at: string;
}

export interface TrendPoint {
  x: number;
  y: number;
}

/** Локальная календарная дата "YYYY-MM-DD" для input[type=date]. */
export function toDateInput(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

/** "2026-10-02T09:00:00Z" -> "02.10.2026" (локальная дата пользователя). */
export function formatMeasuredDate(iso: string): string {
  const date = new Date(iso);
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  return `${day}.${month}.${date.getFullYear()}`;
}

/**
 * ISO-момент замера из выбранной даты. Сегодня → «сейчас» (порядок внутри дня по времени),
 * другая дата → полдень, чтобы сдвиг часового пояса не менял календарный день.
 * При правке записи с той же датой время сохраняется (existingIso).
 */
export function measuredAtFromDate(dateInput: string, now: Date, existingIso?: string): string {
  if (existingIso !== undefined && toDateInput(new Date(existingIso)) === dateInput) {
    return existingIso;
  }
  if (dateInput === toDateInput(now)) {
    return now.toISOString();
  }
  const [year, month, day] = dateInput.split("-").map(Number);
  return new Date(year, month - 1, day, 12, 0, 0).toISOString();
}

/** Точки линии тренда в рамке width×height с отступом pad; записи — в любом порядке. */
export function trendPoints(entries: TrendEntry[], width: number, height: number, pad = 12): TrendPoint[] {
  if (entries.length === 0) {
    return [];
  }
  const sorted = [...entries].sort((a, b) => new Date(a.measured_at).getTime() - new Date(b.measured_at).getTime());
  const times = sorted.map((e) => new Date(e.measured_at).getTime());
  const values = sorted.map((e) => Number(e.value));
  const minT = times[0];
  const maxT = times[times.length - 1];
  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  const innerW = width - 2 * pad;
  const innerH = height - 2 * pad;
  return sorted.map((_, i) => ({
    x: maxT === minT ? width / 2 : pad + ((times[i] - minT) / (maxT - minT)) * innerW,
    y: maxV === minV ? height / 2 : pad + (1 - (values[i] - minV) / (maxV - minV)) * innerH,
  }));
}

/** Разница последнего и предыдущего замера (список — новые сверху); null, если замер один. */
export function latestDelta(itemsNewestFirst: TrendEntry[]): number | null {
  if (itemsNewestFirst.length < 2) {
    return null;
  }
  return Math.round((Number(itemsNewestFirst[0].value) - Number(itemsNewestFirst[1].value)) * 100) / 100;
}
