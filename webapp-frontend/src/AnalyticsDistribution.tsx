import { useState, type ReactNode } from "react";

import type { AnalyticsDistributionV2 } from "./apiV2";
import type { MetricKey } from "./analyticsMetric";
import {
  categoryColors,
  donutRings,
  formatPercent,
  formatCount,
  formatTableMinutes,
  ringArcPath,
} from "./analyticsDistributionModel";
import { formatMinutes } from "./analyticsMetric";

const SIZE = 180;
const CENTER = SIZE / 2;
// Внутреннее кольцо — категории, внешнее — подкатегории.
const INNER = { from: 40, to: 62 };
const OUTER = { from: 65, to: 86 };

function formatValue(value: number, metric: MetricKey): string {
  return metric === "minutes" ? formatMinutes(Math.round(value)) : formatCount(value);
}

type DonutProps = {
  dist: AnalyticsDistributionV2;
  metric: MetricKey;
  /** Порядок категорий Главной: цвет категории — по имени, как на Главной (#286). */
  homeOrder?: string[];
  /** Кнопка справа от заголовка («ⓘ»). */
  titleAction?: ReactNode;
};

/** «По типам»: кольцевая диаграмма выбранной метрики/периода + легенда (цвета `--vp-cat-*`). */
export function DistributionDonut({ dist, metric, homeOrder = [], titleAction }: DonutProps) {
  const { inner, outer, total } = donutRings(dist, metric, homeOrder);
  const colors = categoryColors(dist, homeOrder);
  const legend = inner;
  return (
    <div className="profile-card analytics-distribution-card" data-testid="analytics-distribution">
      <div className="analytics-card-title-row">
        <p className="section-title">По типам</p>
        {titleAction}
      </div>
      {total === 0 ? (
        <p className="hint" data-testid="analytics-distribution-empty">За выбранный период нет данных.</p>
      ) : (
        <>
          <svg
            className="analytics-donut" viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" data-testid="analytics-donut"
            aria-label={`Распределение: ${legend.map((s) => `${s.label} ${formatPercent(s.value, total)}`).join(", ")}`}
          >
            {inner.map((seg) => (
              <path
                key={seg.key} d={ringArcPath(CENTER, CENTER, INNER.from, INNER.to, seg.start, seg.end)}
                style={{ fill: seg.color }} data-testid="donut-inner-segment"
              />
            ))}
            {outer.map((seg) => (
              <path
                key={seg.key} d={ringArcPath(CENTER, CENTER, OUTER.from, OUTER.to, seg.start, seg.end)}
                style={{ fill: seg.color }} fillOpacity={seg.opacity} data-testid="donut-outer-segment"
              />
            ))}
            <text x={CENTER} y={CENTER - 2} textAnchor="middle" className="analytics-donut-total">{formatValue(total, metric)}</text>
            <text x={CENTER} y={CENTER + 12} textAnchor="middle" className="analytics-donut-caption">всего</text>
          </svg>
          <ul className="analytics-legend" data-testid="analytics-legend">
            {legend.map((seg) => (
              <li key={seg.key} data-testid="analytics-legend-item">
                <span className="analytics-legend-swatch" style={{ background: colors.get(seg.label) }} aria-hidden="true" />
                <span className="analytics-legend-name" title={seg.label}>{seg.label}</span>
                <span className="analytics-legend-value">{formatValue(seg.value, metric)} · {formatPercent(seg.value, total)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

type Category = AnalyticsDistributionV2["categories"][number];

/** Ненулевая строка: есть хотя бы одна тренировка или минута (значения целые, #308). */
function hasValue(item: { workouts: number; minutes: number }): boolean {
  return item.workouts >= 1 || item.minutes >= 1;
}

/** «Сводка»: по умолчанию только строки с данными, «Показать все» раскрывает нули каталога;
 * колонки Тренировки / Минуты, строка «Итого». */
export function DistributionTable({ dist, homeOrder = [] }: { dist: AnalyticsDistributionV2; homeOrder?: string[] }) {
  const [showAll, setShowAll] = useState(false);
  const colors = categoryColors(dist, homeOrder);
  const visible = showAll ? dist.categories : dist.categories.filter(hasValue);
  // Честный счётчик: сколько строк добавит «Показать все» (все строки минус сейчас видимые).
  const allRows = dist.categories.reduce((sum, category) => sum + 1 + category.subcategories.length, 0);
  const shownRows = dist.categories
    .filter(hasValue)
    .reduce((sum, category) => sum + 1 + category.subcategories.filter(hasValue).length, 0);
  const hiddenCount = allRows - shownRows;
  // Нет ни одной строки с данными (новый пользователь): раскрывать нечего, кроме нулей каталога — без кнопки (#290).
  return (
    <div className="profile-card analytics-summary-card" data-testid="analytics-summary">
      <p className="section-title">Сводка</p>
      <table className="analytics-summary-table">
        <thead>
          <tr><th scope="col">Тип</th><th scope="col">Тренировки</th><th scope="col">Минуты</th></tr>
        </thead>
        <tbody>
          {visible.map((category) => (
            <SummaryRows key={category.name} category={category} color={colors.get(category.name)} showAll={showAll} />
          ))}
          <tr className="analytics-summary-total" data-testid="summary-total">
            <th scope="row">Итого</th>
            <td>{formatCount(dist.total_workouts)}</td>
            <td>{formatTableMinutes(dist.total_minutes)}</td>
          </tr>
        </tbody>
      </table>
      {((hiddenCount > 0 && shownRows > 0) || showAll) && (
        <button
          type="button" className="analytics-show-all" data-testid="summary-show-all" aria-expanded={showAll}
          onClick={() => setShowAll((value) => !value)}
        >
          {showAll ? "Скрыть пустые" : `Показать все (+${hiddenCount})`}
        </button>
      )}
    </div>
  );
}

function SummaryRows({ category, color, showAll }: { category: Category; color?: string; showAll: boolean }) {
  const subs = showAll ? category.subcategories : category.subcategories.filter(hasValue);
  return (
    <>
      <tr data-testid="summary-category" data-category={category.name}>
        <th scope="row" title={category.name}>
          {color !== undefined && <span className="analytics-legend-swatch analytics-summary-swatch" style={{ background: color }} aria-hidden="true" />}
          {category.name}
        </th>
        <td>{formatCount(category.workouts)}</td>
        <td>{formatTableMinutes(category.minutes)}</td>
      </tr>
      {subs.map((sub) => (
        <tr key={sub.name} className="analytics-summary-sub" data-testid="summary-subcategory" data-category={category.name}>
          <th scope="row" title={sub.name}>{sub.name}</th>
          <td>{formatCount(sub.workouts)}</td>
          <td>{formatTableMinutes(sub.minutes)}</td>
        </tr>
      ))}
    </>
  );
}
