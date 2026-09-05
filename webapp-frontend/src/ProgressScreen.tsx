import { useEffect, useState, type PointerEvent } from "react";

import { fetchAnalytics, fetchProgress, type AnalyticsData, type EquipmentProgress, type ProgressPoint } from "./api";

type Props = { initDataRaw: string };

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; points: ProgressPoint[]; analytics: AnalyticsData };

// Категориальная пара из справочника dataviz-скилла (references/palette.md,
// слоты 1/2 — blue/orange), провалидированная на contrast/CVD-различимость
// соседней пары — не подобрана на глаз.
const SERIES_A_COLOR = "#2a78d6";
const SERIES_B_COLOR = "#eb6834";

const CHART_WIDTH = 320;
const CHART_HEIGHT = 200;
const PADDING_LEFT = 30;
const PADDING_RIGHT = 14;
const PADDING_TOP = 16;
const PADDING_BOTTOM = 22;

/** "2026-09-03" -> "03.09" — без года: график про относительный ход
 * тренировок, не про календарь, короче для тесной мобильной ширины. */
function formatDate(isoDate: string): string {
  const [, month, day] = isoDate.split("-");
  return `${day}.${month}`;
}

/** Лёгкий самописный inline-SVG line chart (issue #50, волна 2) — без новой
 * npm-зависимости (recharts и подобные не добавлены, доступность npm из
 * песочницы непостоянна, см. CLAUDE.md; для двух линий с ховером своя
 * реализация дешевле, чем непроверяемо интегрировать библиотеку). Одна общая
 * ось Y — оба блока меряются в тех же повторениях, отдельная ось для
 * второй серии не нужна (dataviz-скилл: "never a dual-axis chart"). */
function LineChart({ points }: { points: ProgressPoint[] }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const plotWidth = CHART_WIDTH - PADDING_LEFT - PADDING_RIGHT;
  const plotHeight = CHART_HEIGHT - PADDING_TOP - PADDING_BOTTOM;

  const values = points.flatMap((point) => [point.target_a, point.target_b]);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const valueRange = maxValue - minValue || 1;
  const lastIndex = points.length - 1;

  function xAt(index: number): number {
    if (points.length === 1) {
      return PADDING_LEFT + plotWidth / 2;
    }
    return PADDING_LEFT + (index / lastIndex) * plotWidth;
  }
  function yAt(value: number): number {
    return PADDING_TOP + plotHeight - ((value - minValue) / valueRange) * plotHeight;
  }
  function pathFor(key: "target_a" | "target_b"): string {
    return points.map((point, index) => `${index === 0 ? "M" : "L"}${xAt(index)},${yAt(point[key])}`).join(" ");
  }

  function handlePointerMove(event: PointerEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const relativeX = ((event.clientX - rect.left) / rect.width) * CHART_WIDTH;
    let nearest = 0;
    let nearestDistance = Infinity;
    for (let index = 0; index < points.length; index += 1) {
      const distance = Math.abs(xAt(index) - relativeX);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearest = index;
      }
    }
    setHoverIndex(nearest);
  }

  const gridValues = [minValue, (minValue + maxValue) / 2, maxValue];
  const hovered = hoverIndex !== null ? points[hoverIndex] : null;

  return (
    <div className="progress-chart-wrap">
      <svg
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        className="progress-chart"
        onPointerMove={handlePointerMove}
        onPointerLeave={() => setHoverIndex(null)}
        role="img"
        aria-label="График цели за подход по тренировкам, блок объёма и блок силы"
      >
        {gridValues.map((value, index) => (
          <g key={index}>
            <line
              x1={PADDING_LEFT} x2={CHART_WIDTH - PADDING_RIGHT} y1={yAt(value)} y2={yAt(value)}
              className="progress-chart-grid"
            />
            <text x={0} y={yAt(value) + 3} className="progress-chart-axis-label">
              {Math.round(value)}
            </text>
          </g>
        ))}

        <text x={PADDING_LEFT} y={CHART_HEIGHT - 4} className="progress-chart-axis-label">
          {formatDate(points[0].performed_at)}
        </text>
        <text x={CHART_WIDTH - PADDING_RIGHT} y={CHART_HEIGHT - 4} textAnchor="end" className="progress-chart-axis-label">
          {formatDate(points[lastIndex].performed_at)}
        </text>

        <path d={pathFor("target_a")} className="progress-chart-line" stroke={SERIES_A_COLOR} />
        <path d={pathFor("target_b")} className="progress-chart-line" stroke={SERIES_B_COLOR} />

        {/* Значение у конца линии (dataviz-скилл: "Lines -> value at the end") — не подписываем каждую точку. */}
        <circle
          cx={xAt(lastIndex)} cy={yAt(points[lastIndex].target_a)} r={4}
          fill={SERIES_A_COLOR} className="progress-chart-end-dot"
        />
        <circle
          cx={xAt(lastIndex)} cy={yAt(points[lastIndex].target_b)} r={4}
          fill={SERIES_B_COLOR} className="progress-chart-end-dot"
        />
        <text
          x={xAt(lastIndex) - 8} y={yAt(points[lastIndex].target_a) - 8} textAnchor="end"
          className="progress-chart-end-label" fill={SERIES_A_COLOR}
        >
          {points[lastIndex].target_a}
        </text>
        <text
          x={xAt(lastIndex) - 8} y={yAt(points[lastIndex].target_b) - 8} textAnchor="end"
          className="progress-chart-end-label" fill={SERIES_B_COLOR}
        >
          {points[lastIndex].target_b}
        </text>

        {hoverIndex !== null && hovered && (
          <g>
            <line
              x1={xAt(hoverIndex)} x2={xAt(hoverIndex)} y1={PADDING_TOP} y2={CHART_HEIGHT - PADDING_BOTTOM}
              className="progress-chart-crosshair"
            />
            <circle cx={xAt(hoverIndex)} cy={yAt(hovered.target_a)} r={4} fill={SERIES_A_COLOR} className="progress-chart-hover-dot" />
            <circle cx={xAt(hoverIndex)} cy={yAt(hovered.target_b)} r={4} fill={SERIES_B_COLOR} className="progress-chart-hover-dot" />
          </g>
        )}
      </svg>

      {hovered && (
        <div className="progress-chart-tooltip">
          <p className="progress-chart-tooltip-date">{formatDate(hovered.performed_at)}</p>
          <p>
            <span className="progress-chart-swatch" style={{ background: SERIES_A_COLOR }} />
            Объём: <strong>{hovered.target_a}</strong>
          </p>
          <p>
            <span className="progress-chart-swatch" style={{ background: SERIES_B_COLOR }} />
            Сила: <strong>{hovered.target_b}</strong>
          </p>
        </div>
      )}

      <div className="progress-chart-legend">
        <span className="progress-chart-legend-item">
          <span className="progress-chart-swatch" style={{ background: SERIES_A_COLOR }} /> Объём
        </span>
        <span className="progress-chart-legend-item">
          <span className="progress-chart-swatch" style={{ background: SERIES_B_COLOR }} /> Сила
        </span>
      </div>
    </div>
  );
}

/** "+12.3%"/"-5%"/без изменений — тот же принцип знака, что _signed_pct
 * бота (app/bot/formatting.py): "+", если >= 0, минус уже есть в самом
 * числе для отрицательных. */
function formatPct(pct: number | null): string {
  if (pct === null) {
    return "нет данных для сравнения";
  }
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct}%`;
}

/** Карточка "динамика на текущем снаряде" (issue #66, п.2) — тот же смысл,
 * что EQUIPMENT_PROGRESS_WITH_PCT бота ("с этой резиной делал 40, сейчас 80,
 * +100%"). */
function EquipmentProgressCard({ title, progress }: { title: string; progress: EquipmentProgress | null }) {
  if (progress === null) {
    return null;
  }
  return (
    <div className="profile-card">
      <p className="section-title">{title}</p>
      <p>{progress.equipment.label}</p>
      <p>
        {progress.first_volume} → {progress.current_volume} ({formatPct(progress.change_pct)})
      </p>
    </div>
  );
}

/** Аналитический блок вкладки "Прогресс" (issue #66, п.2) — те же
 * app.domain.reports вычисления, что кнопки "📊 Прогресс"/"📈 Аналитика по
 * всем циклам" бота (GET /api/analytics), под графиком цели за подход. */
function AnalyticsSection({ analytics }: { analytics: AnalyticsData }) {
  if (!analytics.has_data || analytics.weekly === null) {
    return null;
  }
  const { weekly } = analytics;
  const changedBlocks = [weekly.equipment_changed_a && "объём", weekly.equipment_changed_b && "сила"].filter(Boolean);

  return (
    <div>
      <div className="profile-card">
        <p className="section-title">За неделю</p>
        <p>Тренировок: {weekly.workout_count}</p>
        <p>
          Объём: {weekly.total_volume} ({formatPct(weekly.volume_change_pct)})
        </p>
        {changedBlocks.length > 0 && <p className="hint">Сменился снаряд: {changedBlocks.join(", ")}</p>}
      </div>

      <EquipmentProgressCard title="Динамика — объём" progress={analytics.equipment_progress_a} />
      <EquipmentProgressCard title="Динамика — сила" progress={analytics.equipment_progress_b} />

      {analytics.cycles.length > 0 && (
        <div className="profile-card">
          <p className="section-title">
            Аналитика по циклам (всего {analytics.total_volume})
          </p>
          {analytics.cycles.map((cycle, index) => (
            <p key={cycle.workout_set_id}>
              Цикл {index + 1}: {cycle.workout_count} тр., объём {cycle.total_volume} ({formatPct(cycle.volume_change_pct)})
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

/** Вкладка "Прогресс" (issue #50, волна 2; аналитика — issue #66, п.2) —
 * цель за подход по тренировкам во времени для блока A и Б (GET /api/progress,
 * прогрессия уже посчитана на бэкенде, здесь не пересчитывается), плюс
 * недельная динамика/прогресс на снаряде/сводка по циклам (GET /api/analytics,
 * те же app.domain.reports вызовы, что кнопки бота). */
export function ProgressScreen({ initDataRaw }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [progress, analytics] = await Promise.all([fetchProgress(initDataRaw), fetchAnalytics(initDataRaw)]);
        if (!cancelled) {
          setState({ phase: "ready", points: progress.points, analytics });
        }
      } catch (error) {
        if (!cancelled) {
          setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  if (state.phase === "loading") {
    return <p className="screen-message">Загружаю прогресс…</p>;
  }
  if (state.phase === "error") {
    return <p className="screen-message">Не удалось загрузить прогресс: {state.message}</p>;
  }

  return (
    <div>
      <p className="plan-title">Прогресс</p>
      {state.points.length < 2 ? (
        <p className="screen-message">Пока недостаточно тренировок для графика — нужно хотя бы две.</p>
      ) : (
        <>
          <p className="hint">Цель за подход по тренировкам</p>
          <LineChart points={state.points} />
        </>
      )}
      <AnalyticsSection analytics={state.analytics} />
    </div>
  );
}
