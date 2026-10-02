// Чистые помощники «Распределение по категориям» (CRIMPD #274): сегменты кольцевой
// диаграммы, цвета, формат дробных значений. Без React и DOM.

import type { AnalyticsDistributionV2 } from "./apiV2";
import type { MetricKey } from "./analyticsMetric";

/** Категориальная палитра проекта: первая пара — из графика «Программа»/аналитики
 * (синий/оранжевый), далее различимые в светлой и тёмной теме оттенки. */
export const CATEGORY_COLORS = ["#2a78d6", "#eb6834", "#2fa36b", "#8e5bd0", "#d6a21f", "#d6457a", "#4a9fb3"] as const;
/** Нейтральный цвет служебной категории «Другая активность» / «Без категории». */
export const NEUTRAL_COLOR = "#8a8f98";
export const OTHER_ACTIVITY = "Другая активность";
export const UNCATEGORIZED = "Без категории";

const EPSILON = 0.005;

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

/** Цвет по порядку категории в ответе; служебные — нейтральные. Порядок стабилен
 * между метриками (берётся из исходного списка), не из отфильтрованного. */
export function categoryColors(dist: AnalyticsDistributionV2): Map<string, string> {
  const colors = new Map<string, string>();
  let index = 0;
  for (const category of dist.categories) {
    if (isServiceCategory(category.name)) {
      colors.set(category.name, NEUTRAL_COLOR);
    } else {
      colors.set(category.name, CATEGORY_COLORS[index % CATEGORY_COLORS.length]);
      index += 1;
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
  dist: AnalyticsDistributionV2, metric: MetricKey,
): { inner: DonutSegment[]; outer: DonutSegment[]; total: number } {
  const colors = categoryColors(dist);
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
