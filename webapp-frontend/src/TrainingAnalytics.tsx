import { useCallback, useEffect, useState } from "react";

import {
  fetchPrograms,
  fetchTrainingAnalytics,
  type AnalyticsExerciseV2,
  type AnalyticsPanelV2,
  type AnalyticsMetricWeekV2,
  type AnalyticsPointV2,
  type TrainingAnalyticsV2,
} from "./apiV2";
import {
  formatMinutes,
  formatWeekLabel,
  localIsoDate,
  presetRange,
  validateCustomRange,
  type DateRange,
  type MetricKey,
  type RangeKey,
} from "./analyticsMetric";
import { formatDuration, formatLongDuration, formatNumber } from "./blockFormat";
import { DistributionDonut, DistributionTable } from "./AnalyticsDistribution";
import { homeCategoryOrder } from "./homeDiscovery";
import { useModalSheet } from "./useModalSheet";
import { Icon } from "./Icon";

type Props = { initDataRaw: string };

type State =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; data: TrainingAnalyticsV2 };

// Цвета — из той же категориальной пары, что график "Программа" (dataviz,
// blue/orange): основной ряд и подсветка рекорда.
const SERIES_COLOR = "#2a78d6";
const PB_COLOR = "#eb6834";
const CHART_POINT_LIMIT = 30;

const PROTOCOL_TITLES = {
  reps_sets: "Повторения",
  time_sets: "Время",
  max_effort: "Максимум",
  interval: "Интервалы",
} as const;

function formatShortDate(iso: string): string {
  const date = new Date(iso);
  return `${String(date.getDate()).padStart(2, "0")}.${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function formatValue(unit: string | null, value: string): string {
  return unit === "s" ? formatDuration(Number(value)) : formatNumber(value);
}

// --- Недельные столбики выбранной метрики ---------------------------------------

const METRIC_TABS: { key: MetricKey; label: string }[] = [
  { key: "workouts", label: "Тренировки" },
  { key: "minutes", label: "Минуты" },
];
const RANGE_TABS: { key: RangeKey; label: string }[] = [
  { key: "1m", label: "1 мес" },
  { key: "3m", label: "3 мес" },
  { key: "custom", label: "Свой" },
];
const VALUE_LABELS_MAX_WEEKS = 14;

function WeeksChart({ weeks, metric }: { weeks: AnalyticsMetricWeekV2[]; metric: MetricKey }) {
  const width = 320;
  const height = 130;
  const left = 8;
  const bottom = 22;
  const top = 16;
  const valueOf = (week: AnalyticsMetricWeekV2) => (metric === "minutes" ? week.minutes : week.workouts);
  const max = Math.max(1, ...weeks.map(valueOf));
  const slot = (width - left * 2) / weeks.length;
  const barWidth = Math.min(slot * 0.62, 28);
  const labelStep = Math.ceil(weeks.length / 6);
  // подписи значений крупнее 11px: показываем, только если помещаются в слот столбца (#290)
  const showValues = weeks.length <= VALUE_LABELS_MAX_WEEKS && slot >= String(max).length * 8.5 + 2;
  const summary = weeks.map((week) => `${formatWeekLabel(week.week_start)}: ${valueOf(week)}`).join(", ");
  const noun = metric === "minutes" ? "Минут" : "Тренировок";
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`} className="analytics-weeks-chart" role="img" data-metric={metric}
      aria-label={`${noun} по неделям (с понедельника): ${summary}`}
    >
      <line x1={left} x2={width - left} y1={height - bottom} y2={height - bottom} stroke="currentColor" opacity="0.25" />
      {weeks.map((week, index) => {
        const value = valueOf(week);
        const barHeight = value === 0 ? 0 : Math.max(3, ((height - bottom - top) * value) / max);
        const x = left + index * slot + (slot - barWidth) / 2;
        return (
          <g key={week.week_start}>
            <rect
              x={x} y={height - bottom - barHeight} width={barWidth} height={barHeight} rx={2}
              fill={SERIES_COLOR} opacity={value === 0 ? 0.15 : 1}
            />
            {showValues && value > 0 && (
              <text x={x + barWidth / 2} y={height - bottom - barHeight - 3} fontSize="14" textAnchor="middle" fill="currentColor">
                {value}
              </text>
            )}
            {index % labelStep === 0 && (
              <text x={x + barWidth / 2} y={height - 7} fontSize="14" textAnchor="middle" fill="currentColor" opacity="0.7">
                {formatWeekLabel(week.week_start)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function MetricInfoSheet({ onClose }: { onClose: () => void }) {
  const dialogRef = useModalSheet(onClose);
  return (
    <div className="home-sheet-backdrop" onClick={onClose}>
      <div
        ref={dialogRef} className="home-sheet" role="dialog" aria-modal="true" aria-label="Что значат метрики" tabIndex={-1}
        data-testid="analytics-info-sheet" onClick={(event) => event.stopPropagation()}>
        <p className="section-title">Что значат метрики</p>
        <p className="hint"><b>Тренировки</b> — сколько завершённых тренировок в неделю, включая те, где время не записано.</p>
        <p className="hint">
          <b>Минуты</b> — сумма длительностей тренировок: от старта до завершения. Берутся только тренировки
          длиной от 1 минуты до 6 часов; остальные считаются как тренировки, но не как минуты.
        </p>
        <p className="hint">Неделя — с понедельника, в вашем часовом поясе.</p>
        <button type="button" className="home-sheet-action home-sheet-cancel" onClick={onClose}>Закрыть</button>
      </div>
    </div>
  );
}

type HeaderProps = {
  metric: MetricKey;
  rangeKey: RangeKey;
  draft: DateRange;
  onMetric: (metric: MetricKey) => void;
  onRange: (range: RangeKey) => void;
  onDraft: (draft: DateRange) => void;
  onApply: () => void;
};

/** Единая шапка Аналитики (#286 C1): слева выпадающий выбор метрики (нативный select), справа
 * подчёркнутые табы периода; «Свой» открывает поля дат строкой ниже. */
function AnalyticsHeader({ metric, rangeKey, draft, onMetric, onRange, onDraft, onApply }: HeaderProps) {
  const draftError = validateCustomRange(draft.from, draft.to);
  return (
    <div data-testid="analytics-header">
      <div className="analytics-header-strip">
        <label className="analytics-metric-select">
          <select
            aria-label="Метрика" value={metric} data-testid="analytics-metric-select"
            onChange={(event) => onMetric(event.target.value as MetricKey)}
          >
            {METRIC_TABS.map((tab) => (
              <option key={tab.key} value={tab.key}>{tab.label}</option>
            ))}
          </select>
          <Icon name="chevronDown" size={14} strokeWidth={2.4} className="analytics-metric-select-caret" />
        </label>
        <div className="workout-mode-buttons vp-tabs analytics-range-tabs" role="tablist" aria-label="Период">
          {RANGE_TABS.map((tab) => (
            <button
              key={tab.key} type="button" role="tab" aria-selected={tab.key === rangeKey}
              className={tab.key === rangeKey ? "leaderboard-tab leaderboard-tab-active" : "leaderboard-tab"}
              onClick={() => onRange(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>
      {rangeKey === "custom" && (
        <div className="analytics-custom-range" data-testid="analytics-custom-range">
          <label>
            С <input type="date" value={draft.from} max={draft.to || undefined} onChange={(e) => onDraft({ ...draft, from: e.target.value })} />
          </label>
          <label>
            По <input type="date" value={draft.to} min={draft.from || undefined} onChange={(e) => onDraft({ ...draft, to: e.target.value })} />
          </label>
          <button type="button" className="leaderboard-tab" disabled={draftError !== null} onClick={onApply}>Применить</button>
          {draftError !== null && <p className="hint">{draftError}</p>}
        </div>
      )}
    </div>
  );
}

function InfoButton({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" className="analytics-info-button" aria-label="Что значат метрики" onClick={onClick}>
      <Icon name="info" size={20} />
    </button>
  );
}

type MetricsProps = HeaderProps & { data: TrainingAnalyticsV2; homeOrder: string[] };

/** Блоки выбранной метрики: порядок как в эталоне — сначала «по типам» (кольцо + легенда),
 * затем недельные столбики, затем сводка. */
function MetricsBlocks({ data, metric, homeOrder, ...header }: MetricsProps) {
  const [infoOpen, setInfoOpen] = useState(false);
  const { metrics } = data;
  const total = metric === "minutes" ? formatMinutes(metrics.total_minutes) : `${metrics.total_workouts}`;
  return (
    <div data-testid="analytics-metrics">
      <AnalyticsHeader metric={metric} {...header} />
      <div className="analytics-stat-grid analytics-activity-cards" data-testid="analytics-kpi-row">
        <Stat label="Тренировок за 30 дней" value={String(data.activity.sessions_last_30_days)} />
        <Stat label="Активных дней за 30 дней" value={String(data.activity.active_days_last_30_days)} />
      </div>
      <DistributionDonut
        dist={data.distribution} metric={metric} homeOrder={homeOrder}
        titleAction={<InfoButton onClick={() => setInfoOpen(true)} />}
      />
      <div className="profile-card analytics-weeks-card" data-testid="analytics-weeks">
        <p className="section-title">{metric === "minutes" ? "Минуты по неделям" : "Тренировки по неделям"}</p>
        <WeeksChart weeks={metrics.weeks} metric={metric} />
        <p className="hint" data-testid="analytics-metric-total">
          {metric === "minutes" ? "Всего минут" : "Всего тренировок"}: {total}
          {" · "}{formatWeekLabel(metrics.date_from)} – {formatWeekLabel(metrics.date_to)}
        </p>
        {metric === "minutes" && metrics.without_duration > 0 && (
          <p className="hint" data-testid="analytics-no-duration">без данных о времени: {metrics.without_duration}</p>
        )}
      </div>
      <DistributionTable dist={data.distribution} homeOrder={homeOrder} />
      <p className="hint analytics-footnote">
        Смешанная тренировка делится между категориями поровну по блокам; минуты — по длительности тренировки.
      </p>
      {infoOpen && <MetricInfoSheet onClose={() => setInfoOpen(false)} />}
    </div>
  );
}

// --- Тренд панели ---------------------------------------------------------------

type ChartPoint = { at: string; y: number; pb: boolean };

function TrendChart({ points, ariaLabel }: { points: ChartPoint[]; ariaLabel: string }) {
  if (points.length < 2) {
    return <p className="hint">Для графика нужно хотя бы две записи.</p>;
  }
  const width = 320;
  const height = 150;
  const left = 46;
  const right = 10;
  const top = 12;
  const bottom = 22;
  const ys = points.map((point) => point.y);
  const min = Math.min(...ys);
  const max = Math.max(...ys);
  const span = max - min || 1;
  const x = (index: number) => left + (index * (width - left - right)) / (points.length - 1);
  const y = (value: number) => top + (1 - (value - min) / span) * (height - top - bottom);
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(1)},${y(point.y).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="analytics-trend-chart" role="img" aria-label={ariaLabel}>
      <text x={left - 4} y={y(max) + 3} fontSize="14" textAnchor="end" fill="currentColor" opacity="0.7">{formatNumber(Math.round(max * 10) / 10)}</text>
      <text x={left - 4} y={y(min) + 3} fontSize="14" textAnchor="end" fill="currentColor" opacity="0.7">{formatNumber(Math.round(min * 10) / 10)}</text>
      <path d={path} fill="none" stroke={SERIES_COLOR} strokeWidth="2" strokeLinejoin="round" />
      {points.map((point, index) => (
        <circle key={`${point.at}-${index}`} cx={x(index)} cy={y(point.y)} r={point.pb ? 4.5 : 2.5} fill={point.pb ? PB_COLOR : SERIES_COLOR} />
      ))}
      <text x={left} y={height - 6} fontSize="14" fill="currentColor" opacity="0.7">{formatShortDate(points[0].at)}</text>
      <text x={width - right} y={height - 6} fontSize="14" textAnchor="end" fill="currentColor" opacity="0.7">
        {formatShortDate(points[points.length - 1].at)}
      </text>
    </svg>
  );
}

function pointsFor(panel: AnalyticsPanelV2): ChartPoint[] {
  const shown = panel.points.slice(-CHART_POINT_LIMIT);
  return shown.map((point: AnalyticsPointV2) => ({
    at: point.at,
    y: panel.protocol_type === "max_effort" ? Number(point.cumulative_best ?? point.value) : Number(point.value),
    pb: point.is_new_pb === true,
  }));
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="analytics-stat">
      <p className="analytics-stat-value">{value}</p>
      <p className="analytics-stat-label">{label}</p>
    </div>
  );
}

function Panel({ panel }: { panel: AnalyticsPanelV2 }) {
  const isTimeMax = panel.protocol_type === "max_effort" && panel.unit === "s";
  const title = panel.protocol_type === "max_effort"
    ? (isTimeMax ? "Максимум времени" : "Максимум повторений")
    : PROTOCOL_TITLES[panel.protocol_type];
  const chartPoints = pointsFor(panel);
  const hiddenNote = panel.points_total > chartPoints.length
    ? `Показаны последние ${chartPoints.length} из ${panel.points_total}`
    : null;
  const trendLabel = panel.protocol_type === "max_effort"
    ? "Рекорд по тренировкам (◆ — новый рекорд)"
    : panel.protocol_type === "interval"
      ? "Время интервалов по тренировкам"
      : panel.protocol_type === "time_sets" ? "Время в работе по тренировкам" : "Повторений по тренировкам";

  return (
    <div className="profile-card analytics-panel" data-protocol={panel.protocol_type}>
      <p className="section-title">{title}</p>
      <div className="analytics-stat-grid">
        {panel.protocol_type === "reps_sets" && (
          <>
            <Stat label="Всего повторений" value={formatNumber(panel.total_reps ?? "0")} />
            <Stat label="Подходов" value={String(panel.set_count ?? 0)} />
            <Stat label="Лучший подход" value={formatNumber(panel.best_set ?? "0")} />
          </>
        )}
        {panel.protocol_type === "time_sets" && (
          <>
            <Stat label="Время в работе" value={formatLongDuration(Number(panel.total_work_seconds ?? 0))} />
            <Stat label="Подходов" value={String(panel.set_count ?? 0)} />
            <Stat label="Лучшая длительность" value={formatDuration(Number(panel.best_set ?? 0))} />
          </>
        )}
        {panel.protocol_type === "max_effort" && (
          <>
            <Stat label="Попыток" value={String(panel.attempt_count ?? 0)} />
            <Stat label="Лучший результат" value={formatValue(panel.unit, panel.best ?? "0")} />
            <Stat label="Тренировок" value={String(panel.session_count)} />
          </>
        )}
        {panel.protocol_type === "interval" && (
          <>
            <Stat label="Время интервалов" value={formatLongDuration(panel.actual_duration_seconds ?? 0)} />
            <Stat label="Интервалов" value={String(panel.cycles ?? 0)} />
            <Stat label="Тренировок" value={String(panel.session_count)} />
          </>
        )}
      </div>
      <p className="hint">{trendLabel}</p>
      <TrendChart points={chartPoints} ariaLabel={`${title}: ${trendLabel}`} />
      {hiddenNote !== null && <p className="hint">{hiddenNote}</p>}
    </div>
  );
}

function ExerciseSection({ exercise }: { exercise: AnalyticsExerciseV2 }) {
  return (
    <div>
      {exercise.panels.map((panel) => (
        <Panel key={panel.protocol_type} panel={panel} />
      ))}
    </div>
  );
}

/** Аналитика тренировок (TrainingSession v2): активность за 30 дней, недельные
 * столбики «Тренировки | Минуты» за 1 мес / 3 мес / свой период, выбор
 * упражнения, панели по протоколам. Несовместимые протоколы одного упражнения
 * показываются отдельными панелями, никогда не суммируются. */
export function TrainingAnalytics({ initDataRaw }: Props) {
  const [state, setState] = useState<State>({ phase: "loading" });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [metric, setMetric] = useState<MetricKey>("workouts");
  const [rangeKey, setRangeKey] = useState<RangeKey>("1m");
  // Применённый диапазон; undefined — серверный дефолт «1 мес» (последние 30 локальных дней).
  const [request, setRequest] = useState<DateRange | undefined>(undefined);
  const [draft, setDraft] = useState<DateRange>({ from: "", to: "" });
  // Порядок категорий на Главной — цвет категории по имени, одинаковый на Главной и в Аналитике (#286).
  const [homeOrder, setHomeOrder] = useState<string[]>([]);
  const requestFrom = request?.from;
  const requestTo = request?.to;

  const load = useCallback(() => {
    let cancelled = false;
    // При смене диапазона прежние данные остаются на экране до прихода новых.
    setState((previous) => (previous.phase === "ready" ? previous : { phase: "loading" }));
    const range = requestFrom !== undefined && requestTo !== undefined ? { from: requestFrom, to: requestTo } : undefined;
    fetchTrainingAnalytics(initDataRaw, range)
      .then((data) => {
        if (!cancelled) {
          setState({ phase: "ready", data });
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw, requestFrom, requestTo]);

  useEffect(() => load(), [load]);

  useEffect(() => {
    let cancelled = false;
    fetchPrograms(initDataRaw)
      .then((programs) => !cancelled && setHomeOrder(homeCategoryOrder(programs)))
      .catch(() => undefined); // без каталога цвета — стабильный хеш имени
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  const todayIso = (): string => {
    const timeZone = state.phase === "ready" ? state.data.timezone : Intl.DateTimeFormat().resolvedOptions().timeZone;
    return localIsoDate(new Date(), timeZone);
  };
  const selectRange = (next: RangeKey) => {
    setRangeKey(next);
    if (next === "custom") {
      setDraft(request ?? presetRange("1m", todayIso()));
    } else {
      setRequest(next === "1m" ? undefined : presetRange("3m", todayIso()));
    }
  };

  if (state.phase === "loading") {
    return <p className="screen-message">Загружаю аналитику тренировок…</p>;
  }
  if (state.phase === "error") {
    return (
      <div>
        <p className="screen-message">Не удалось загрузить аналитику тренировок: {state.message}</p>
        <button type="button" className="leaderboard-tab" onClick={() => load()}>Повторить</button>
        <p className="hint">Аналитика по программе доступна на вкладке «Программа».</p>
      </div>
    );
  }

  const { data } = state;
  const selected = data.exercises.find((exercise) => exercise.exercise_id === selectedId) ?? data.exercises[0] ?? null;

  return (
    <div>
      <MetricsBlocks
        data={data} homeOrder={homeOrder} metric={metric} rangeKey={rangeKey} draft={draft}
        onMetric={setMetric} onRange={selectRange} onDraft={setDraft}
        onApply={() => setRequest({ ...draft })}
      />

      {data.exercises.length === 0 ? (
        <p className="screen-message">
          Пока нет завершённых тренировок из «Мои тренировки» — показатели по упражнениям появятся после первой.
        </p>
      ) : (
        <>
          <p className="section-title">Упражнение</p>
          <div className="workout-mode-buttons analytics-exercise-picker">
            {data.exercises.map((exercise) => (
              <button
                key={exercise.exercise_id}
                type="button"
                className={
                  exercise.exercise_id === selected?.exercise_id ? "leaderboard-tab leaderboard-tab-active" : "leaderboard-tab"
                }
                onClick={() => setSelectedId(exercise.exercise_id)}
              >
                {exercise.exercise_name}
              </button>
            ))}
          </div>
          {selected !== null && <ExerciseSection exercise={selected} />}
        </>
      )}
    </div>
  );
}
