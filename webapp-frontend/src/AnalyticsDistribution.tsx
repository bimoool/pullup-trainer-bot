import type { AnalyticsDistributionV2 } from "./apiV2";
import type { MetricKey } from "./analyticsMetric";
import {
  categoryColors,
  donutRings,
  formatPercent,
  formatShare,
  formatTableMinutes,
  ringArcPath,
} from "./analyticsDistribution";
import { formatMinutes } from "./analyticsMetric";

const SIZE = 180;
const CENTER = SIZE / 2;
// Внутреннее кольцо — категории, внешнее — подкатегории.
const INNER = { from: 40, to: 62 };
const OUTER = { from: 65, to: 86 };

function formatValue(value: number, metric: MetricKey): string {
  return metric === "minutes" ? formatMinutes(Math.round(value)) : formatShare(value);
}

/** «По типам»: кольцевая диаграмма выбранной метрики/периода + легенда. */
export function DistributionDonut({ dist, metric }: { dist: AnalyticsDistributionV2; metric: MetricKey }) {
  const { inner, outer, total } = donutRings(dist, metric);
  const colors = categoryColors(dist);
  const legend = inner;
  return (
    <div data-testid="analytics-distribution">
      <p className="section-title">По типам</p>
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
                fill={seg.color} data-testid="donut-inner-segment"
              />
            ))}
            {outer.map((seg) => (
              <path
                key={seg.key} d={ringArcPath(CENTER, CENTER, OUTER.from, OUTER.to, seg.start, seg.end)}
                fill={seg.color} fillOpacity={seg.opacity} data-testid="donut-outer-segment"
              />
            ))}
          </svg>
          <ul className="analytics-legend" data-testid="analytics-legend">
            {legend.map((seg) => (
              <li key={seg.key} data-testid="analytics-legend-item">
                <span className="analytics-legend-swatch" style={{ background: colors.get(seg.label) }} aria-hidden="true" />
                <span className="analytics-legend-name">{seg.label}</span>
                <span className="analytics-legend-value">{formatValue(seg.value, metric)} · {formatPercent(seg.value, total)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

/** «Сводка»: категории (+ подкатегории), колонки Тренировки / Минуты, строка ВСЕГО; нули — для категорий каталога. */
export function DistributionTable({ dist }: { dist: AnalyticsDistributionV2 }) {
  return (
    <div data-testid="analytics-summary">
      <p className="section-title">Сводка</p>
      <table className="analytics-summary-table">
        <thead>
          <tr><th scope="col">Тип</th><th scope="col">Тренировки</th><th scope="col">Минуты</th></tr>
        </thead>
        <tbody>
          {dist.categories.map((category) => (
            <SummaryRows key={category.name} category={category} />
          ))}
          <tr className="analytics-summary-total" data-testid="summary-total">
            <th scope="row">TOTAL</th>
            <td>{formatShare(dist.total_workouts)}</td>
            <td>{formatTableMinutes(dist.total_minutes)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function SummaryRows({ category }: { category: AnalyticsDistributionV2["categories"][number] }) {
  return (
    <>
      <tr data-testid="summary-category" data-category={category.name}>
        <th scope="row">{category.name}</th>
        <td>{formatShare(category.workouts)}</td>
        <td>{formatTableMinutes(category.minutes)}</td>
      </tr>
      {category.subcategories.map((sub) => (
        <tr key={sub.name} className="analytics-summary-sub" data-testid="summary-subcategory" data-category={category.name}>
          <th scope="row">{sub.name}</th>
          <td>{formatShare(sub.workouts)}</td>
          <td>{formatTableMinutes(sub.minutes)}</td>
        </tr>
      ))}
    </>
  );
}
