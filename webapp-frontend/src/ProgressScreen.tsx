import { useEffect, useState, type PointerEvent } from "react";

import {
  fetchAnalytics,
  fetchProgress,
  type AnalyticsData,
  type EquipmentProgress,
  type ProgressMetric,
  type ProgressPoint,
} from "./api";
import { LeaderboardScreen } from "./LeaderboardScreen";

type Props = { initDataRaw: string };

type ProgressState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; points: ProgressPoint[] };

type AnalyticsState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; analytics: AnalyticsData };

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

type SeriesKey = "value_a" | "value_b";

/** Точка графика с числами вместо строк Decimal — конвертация происходит
 * один раз при рендере (issue #82), не в каждой функции chart-компонента. */
type ChartPoint = { performed_at: string; value_a: number | null; value_b: number | null };

/** "strength" (issue #82) — единственная метрика с одной линией (блок Б),
 * не двумя: value_a у неё всегда null (см. app/web/routes.py::_progress_value
 * и объяснение в CLAUDE.md, почему "сила" скоуплена на блок Б). */
function seriesKeysForMetric(metric: ProgressMetric): SeriesKey[] {
  return metric === "strength" ? ["value_b"] : ["value_a", "value_b"];
}

const CHART_METRIC_TABS: { key: ProgressMetric; label: string }[] = [
  { key: "max_reps", label: "Максимум" },
  { key: "volume", label: "Объём" },
  { key: "strength", label: "Сила" },
];

// Пояснение под табами (тот же приём, что METRIC_HINTS в LeaderboardScreen,
// issue #74, волна 3.2) — подписи табов сами по себе не объясняют методику.
const CHART_METRIC_HINTS: Record<ProgressMetric, string> = {
  max_reps: "Лучший фактический подход блока (рабочий или на максимум) — не плановая цель.",
  volume: "Сумма повторений блока (рабочие подходы + подход на максимум) за тренировку.",
  strength:
    "Нагрузка блока «Сила» на единой шкале: резина — со знаком минус, 0 — свой вес, " +
    "отягощение — со знаком плюс. Переживает смену снаряда, в отличие от повторений. " +
    'Тренировки на "австралийских" подтягиваниях (без снаряда в кг) на график не попадают.',
};

const SERIES_LABELS: Record<ProgressMetric, Partial<Record<SeriesKey, string>>> = {
  max_reps: { value_a: "Объём", value_b: "Сила" },
  volume: { value_a: "Объём", value_b: "Сила" },
  strength: { value_b: "Блок Б" },
};

const SERIES_COLOR: Record<SeriesKey, string> = {
  value_a: SERIES_A_COLOR,
  value_b: SERIES_B_COLOR,
};

/** "2026-09-03" -> "03.09" — без года: график про относительный ход
 * тренировок, не про календарь, короче для тесной мобильной ширины. */
function formatDate(isoDate: string): string {
  const [, month, day] = isoDate.split("-");
  return `${day}.${month}`;
}

/** Повторения/объём — целое число; "сила" — кг со знаком (уже есть в самом
 * числе для отрицательных, "+" добавляется только для положительных, чтобы
 * "прибавка отягощения" отличалась от "0 — свой вес" на глаз). */
function formatMetricValue(metric: ProgressMetric, value: number): string {
  if (metric === "strength") {
    const sign = value > 0 ? "+" : "";
    return `${sign}${value} кг`;
  }
  return `${Math.round(value)}`;
}

/** Лёгкий самописный inline-SVG line chart (issue #50, волна 2; issue #82 —
 * факт вместо плана + переменное число серий: 2 для "максимум"/"объём", 1
 * для "сила"). Без новой npm-зависимости (recharts и подобные не добавлены,
 * доступность npm из песочницы непостоянна, см. CLAUDE.md). Одна общая ось
 * Y — обе серии "максимум"/"объём" меряются в тех же повторениях, "сила" не
 * смешивается с ними на одном графике (переключатель метрик, не общая ось). */
function LineChart({ points, seriesKeys, metric }: { points: ChartPoint[]; seriesKeys: SeriesKey[]; metric: ProgressMetric }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const plotWidth = CHART_WIDTH - PADDING_LEFT - PADDING_RIGHT;
  const plotHeight = CHART_HEIGHT - PADDING_TOP - PADDING_BOTTOM;

  // points уже отфильтрованы вызывающей стороной так, что все seriesKeys не
  // null (см. ProgressScreen) — здесь можно смело приводить к number.
  const values = points.flatMap((point) => seriesKeys.map((key) => point[key] as number));
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
  function pathFor(key: SeriesKey): string {
    return points.map((point, index) => `${index === 0 ? "M" : "L"}${xAt(index)},${yAt(point[key] as number)}`).join(" ");
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
  const labels = SERIES_LABELS[metric];

  return (
    <div className="progress-chart-wrap">
      <svg
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        className="progress-chart"
        onPointerMove={handlePointerMove}
        onPointerLeave={() => setHoverIndex(null)}
        role="img"
        aria-label={`График "${CHART_METRIC_TABS.find((tab) => tab.key === metric)?.label}" по тренировкам`}
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

        {seriesKeys.map((key) => (
          <path key={key} d={pathFor(key)} className="progress-chart-line" stroke={SERIES_COLOR[key]} />
        ))}

        {/* Значение у конца линии (dataviz-скилл: "Lines -> value at the end") — не подписываем каждую точку. */}
        {seriesKeys.map((key) => (
          <g key={key}>
            <circle
              cx={xAt(lastIndex)} cy={yAt(points[lastIndex][key] as number)} r={4}
              fill={SERIES_COLOR[key]} className="progress-chart-end-dot"
            />
            <text
              x={xAt(lastIndex) - 8} y={yAt(points[lastIndex][key] as number) - 8} textAnchor="end"
              className="progress-chart-end-label" fill={SERIES_COLOR[key]}
            >
              {formatMetricValue(metric, points[lastIndex][key] as number)}
            </text>
          </g>
        ))}

        {hoverIndex !== null && hovered && (
          <g>
            <line
              x1={xAt(hoverIndex)} x2={xAt(hoverIndex)} y1={PADDING_TOP} y2={CHART_HEIGHT - PADDING_BOTTOM}
              className="progress-chart-crosshair"
            />
            {seriesKeys.map((key) => (
              <circle
                key={key} cx={xAt(hoverIndex)} cy={yAt(hovered[key] as number)} r={4}
                fill={SERIES_COLOR[key]} className="progress-chart-hover-dot"
              />
            ))}
          </g>
        )}
      </svg>

      {hovered && (
        <div className="progress-chart-tooltip">
          <p className="progress-chart-tooltip-date">{formatDate(hovered.performed_at)}</p>
          {seriesKeys.map((key) => (
            <p key={key}>
              <span className="progress-chart-swatch" style={{ background: SERIES_COLOR[key] }} />
              {labels[key]}: <strong>{formatMetricValue(metric, hovered[key] as number)}</strong>
            </p>
          ))}
        </div>
      )}

      <div className="progress-chart-legend">
        {seriesKeys.map((key) => (
          <span key={key} className="progress-chart-legend-item">
            <span className="progress-chart-swatch" style={{ background: SERIES_COLOR[key] }} /> {labels[key]}
          </span>
        ))}
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
 * всем циклам" бота (GET /api/analytics), под графиком. Не зависит от
 * выбранной метрики графика — свой независимый запрос (issue #82). */
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

type ProgressSection = "chart" | "leaderboard";

const PROGRESS_SECTIONS: { key: ProgressSection; label: string }[] = [
  { key: "chart", label: "📈 График" },
  { key: "leaderboard", label: "🏆 Лидерборд" },
];

/** Вкладка "Прогресс" (issue #50, волна 2; аналитика — issue #66, п.2;
 * график переделан с плана на факт + переключатель метрик — issue #82) —
 * ФАКТ по тренировкам во времени (GET /api/progress?metric=...), плюс
 * недельная динамика/прогресс на снаряде/сводка по циклам (GET
 * /api/analytics, те же app.domain.reports вызовы, что кнопки бота, не
 * зависят от выбранной метрики графика).
 *
 * "Лидерборд" (issue #67) переехал сюда под-разделом (issue #74, волна 4) —
 * нижнее меню разрослось до 6 пунктов и названия переставали помещаться;
 * логически ближе к "Прогрессу", чем к "Профилю" — оба про динамику
 * результатов, просто свою и относительно других. LeaderboardScreen
 * переиспользуется целиком, не копируется — тот же приём, что
 * AchievementsScreen внутри "Профиля". */
export function ProgressScreen({ initDataRaw }: Props) {
  const [section, setSection] = useState<ProgressSection>("chart");
  const [metric, setMetric] = useState<ProgressMetric>("max_reps");
  const [progressState, setProgressState] = useState<ProgressState>({ phase: "loading" });
  const [analyticsState, setAnalyticsState] = useState<AnalyticsState>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setProgressState({ phase: "loading" });
      try {
        const progress = await fetchProgress(initDataRaw, metric);
        if (!cancelled) {
          setProgressState({ phase: "ready", points: progress.points });
        }
      } catch (error) {
        if (!cancelled) {
          setProgressState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [initDataRaw, metric]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const analytics = await fetchAnalytics(initDataRaw);
        if (!cancelled) {
          setAnalyticsState({ phase: "ready", analytics });
        }
      } catch (error) {
        if (!cancelled) {
          setAnalyticsState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  const seriesKeys = seriesKeysForMetric(metric);
  const chartPoints: ChartPoint[] =
    progressState.phase === "ready"
      ? progressState.points
          .map((point) => ({
            performed_at: point.performed_at,
            value_a: point.value_a === null ? null : Number(point.value_a),
            value_b: point.value_b === null ? null : Number(point.value_b),
          }))
          .filter((point) => seriesKeys.every((key) => point[key] !== null))
      : [];

  return (
    <div>
      <p className="plan-title">Прогресс</p>

      <div className="workout-mode-buttons">
        {PROGRESS_SECTIONS.map((option) => (
          <button
            key={option.key}
            type="button"
            className={option.key === section ? "leaderboard-tab leaderboard-tab-active" : "leaderboard-tab"}
            onClick={() => setSection(option.key)}
          >
            {option.label}
          </button>
        ))}
      </div>

      {section === "leaderboard" ? (
        <LeaderboardScreen initDataRaw={initDataRaw} />
      ) : (
        <>
          <div className="workout-mode-buttons">
            {CHART_METRIC_TABS.map((tab) => (
              <button
                key={tab.key}
                type="button"
                className={tab.key === metric ? "leaderboard-tab leaderboard-tab-active" : "leaderboard-tab"}
                onClick={() => setMetric(tab.key)}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <p className="hint">{CHART_METRIC_HINTS[metric]}</p>

          {progressState.phase === "loading" && <p className="screen-message">Загружаю прогресс…</p>}
          {progressState.phase === "error" && (
            <p className="screen-message">Не удалось загрузить прогресс: {progressState.message}</p>
          )}
          {progressState.phase === "ready" && (
            <>
              {progressState.points.length < 2 ? (
                <p className="screen-message">Пока недостаточно тренировок для графика — нужно хотя бы две.</p>
              ) : chartPoints.length < 2 ? (
                <p className="screen-message">
                  Недостаточно данных для этой метрики — попробуй другую или другой снаряд блока Б.
                </p>
              ) : (
                <LineChart points={chartPoints} seriesKeys={seriesKeys} metric={metric} />
              )}
            </>
          )}

          {analyticsState.phase === "ready" && <AnalyticsSection analytics={analyticsState.analytics} />}
        </>
      )}
    </div>
  );
}
