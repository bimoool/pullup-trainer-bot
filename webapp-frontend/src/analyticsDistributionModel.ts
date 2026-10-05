// Чистые помощники «Распределение по категориям» (CRIMPD #274): сегменты кольцевой
// диаграммы, цвета, формат дробных значений. Без React и DOM.

import type { AnalyticsDistributionV2 } from "./apiV2";
import type { MetricKey } from "./analyticsMetric";
import { CATEGORY_PALETTE_SIZE, categoryColorVar } from "./homeDiscovery.ts";

const EPSILON = 0.005;

/** Нейтральный цвет служебной категории «Другая активность» / «Без категории». */
export const NEUTRAL_COLOR = "#8a8f98";
export const OTHER_ACTIVITY = "Другая активность";
export const UNCATEGORIZED = "Без категории";

export interface DonutSegment {
  key: string;
  label: string;
  color: string;
  opacity: number;
  value: number;
  /** Доли оборота, 0..1 */
  start: number;
  end: number;
}

export function isServiceCategory(name: string): boolean {
  return name === OTHER_ACTIVITY || name === UNCATEGORIZED;
}

/** Цвет категории — по ИМЕНИ (`categoryColorVar` из homeDiscovery, #286), а не по позиции в ответе:
 * Аналитика сортирует категории по числу тренировок, Главная — по порядку программ, поэтому
 * позиционное совпадение давало разные цвета одной категории. `homeOrder` — порядок рядов Главной
 * (`homeCategoryOrder(programs)`); служебные категории — нейтральные. Значения — `var(--vp-cat-N)`. */
export function categoryColors(dist: AnalyticsDistributionV2, homeOrder: string[] = []): Map<string, string> {
  const colors = new Map<string, string>();
  const taken = new Set<string>();
  // Цвет по имени; при совпадении внутри одного графика — сдвиг к свободному (только категории с данными,
  // т.е. из легенды; нулевые категории каталога — чистый цвет по имени). Это относится и к категориям Главной:
  // индекс ряда ≥ 6 по модулю палитры совпадает с индексом ряда − 6. Порядок обхода не зависит от сортировки ответа.
  const assign = ({ name, workouts, minutes }: { name: string; workouts: number; minutes: number }) => {
    let color = categoryColorVar(name, homeOrder);
    if (workouts >= EPSILON || minutes >= EPSILON) {
      const start = Number(color.match(/(\d+)\)$/)?.[1] ?? 0);
      for (let step = 1; taken.has(color) && step < CATEGORY_PALETTE_SIZE; step += 1) {
        color = `var(--vp-cat-${(start + step) % CATEGORY_PALETTE_SIZE})`;
      }
      taken.add(color);
    }
    colors.set(name, color);
  };
  const named = dist.categories.filter((c) => !isServiceCategory(c.name));
  const homeIndex = (name: string) => homeOrder.indexOf(name.trim());
  // сначала категории Главной (в порядке рядов — те, что ближе к началу, сохраняют «свой» цвет), затем остальные по имени
  named.filter((c) => homeIndex(c.name) >= 0).sort((x, y) => homeIndex(x.name) - homeIndex(y.name)).forEach(assign);
  named.filter((c) => homeIndex(c.name) < 0).sort((x, y) => x.name.localeCompare(y.name)).forEach(assign);
  for (const category of dist.categories) {
    if (isServiceCategory(category.name)) {
      colors.set(category.name, NEUTRAL_COLOR);
    }
  }
  return colors;
}

function valueOf(item: { workouts: number; minutes: number }, metric: MetricKey): number {
  return metric === "minutes" ? item.minutes : item.workouts;
}

/** Кольца: внутреннее — категории, внешнее — подкатегории (остаток категории без
 * подкатегории — сегмент того же цвета, бледнее). Нулевые значения не рисуются. */
export function donutRings(
  dist: AnalyticsDistributionV2, metric: MetricKey, homeOrder: string[] = [],
): { inner: DonutSegment[]; outer: DonutSegment[]; total: number } {
  const colors = categoryColors(dist, homeOrder);
  const total = dist.categories.reduce((sum, c) => sum + valueOf(c, metric), 0);
  const inner: DonutSegment[] = [];
  const outer: DonutSegment[] = [];
  if (total < EPSILON) {
    return { inner, outer, total: 0 };
  }
  let innerPos = 0;
  let outerPos = 0;
  for (const category of dist.categories) {
    const value = valueOf(category, metric);
    if (value < EPSILON) {
      continue;
    }
    const color = colors.get(category.name) ?? NEUTRAL_COLOR;
    inner.push({
      key: category.name, label: category.name, color, opacity: 1, value,
      start: innerPos / total, end: (innerPos + value) / total,
    });
    innerPos += value;
    const subs = category.subcategories.filter((s) => valueOf(s, metric) >= EPSILON);
    let used = 0;
    subs.forEach((sub, index) => {
      const subValue = valueOf(sub, metric);
      outer.push({
        key: `${category.name}/${sub.name}`, label: sub.name, color,
        opacity: Math.max(0.45, 0.85 - index * 0.15), value: subValue,
        start: outerPos / total, end: (outerPos + subValue) / total,
      });
      outerPos += subValue;
      used += subValue;
    });
    const rest = value - used;
    if (rest >= EPSILON) {
      outer.push({
        key: `${category.name}/`, label: category.name, color, opacity: 0.3, value: rest,
        start: outerPos / total, end: (outerPos + rest) / total,
      });
      outerPos += rest;
    }
  }
  return { inner, outer, total };
}

function point(cx: number, cy: number, radius: number, fraction: number): [number, number] {
  const angle = fraction * 2 * Math.PI - Math.PI / 2;
  return [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)];
}

/** Путь сегмента кольца [rInner, rOuter] между долями оборота; полный круг
 * (одна категория) рисуется чуть меньше оборота, чтобы дуга не вырождалась. */
export function ringArcPath(
  cx: number, cy: number, rInner: number, rOuter: number, start: number, end: number,
): string {
  const to = Math.min(end, start + 0.9999);
  const large = to - start > 0.5 ? 1 : 0;
  const [x1, y1] = point(cx, cy, rOuter, start);
  const [x2, y2] = point(cx, cy, rOuter, to);
  const [x3, y3] = point(cx, cy, rInner, to);
  const [x4, y4] = point(cx, cy, rInner, start);
  const f = (n: number) => n.toFixed(2);
  return `M${f(x1)} ${f(y1)} A${rOuter} ${rOuter} 0 ${large} 1 ${f(x2)} ${f(y2)} L${f(x3)} ${f(y3)} A${rInner} ${rInner} 0 ${large} 0 ${f(x4)} ${f(y4)} Z`;
}

/** Дробные тренировки (смешанная сессия делится по долям блоков): до 2 знаков, без хвостовых нулей. */
export function formatShare(value: number): string {
  return String(Number(value.toFixed(2)));
}

/** Минуты таблицы: округление до целых. */
export function formatTableMinutes(value: number): string {
  return String(Math.round(value));
}

/** Процент доли для легенды: "42%". */
export function formatPercent(value: number, total: number): string {
  return total <= 0 ? "0%" : `${Math.round((value / total) * 100)}%`;
}
