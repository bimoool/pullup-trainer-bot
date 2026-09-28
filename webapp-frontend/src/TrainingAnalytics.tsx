import { useCallback, useEffect, useState } from "react";

import {
  fetchTrainingAnalytics,
  type AnalyticsExerciseV2,
  type AnalyticsPanelV2,
  type AnalyticsPointV2,
  type AnalyticsWeekV2,
  type TrainingAnalyticsV2,
} from "./apiV2";
import { formatDuration, formatLongDuration, formatNumber } from "./blockFormat";

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

/** "2026-09-28" -> "28.09" */
function formatWeekLabel(isoDate: string): string {
  const [, month, day] = isoDate.split("-");
  return `${day}.${month}`;
}

function formatShortDate(iso: string): string {
  const date = new Date(iso);
  return `${String(date.getDate()).padStart(2, "0")}.${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function formatValue(unit: string | null, value: string): string {
  return unit === "s" ? formatDuration(Number(value)) : formatNumber(value);
}

// --- Активность за 12 недель --------------------------------------------------

function WeeksChart({ weeks }: { weeks: AnalyticsWeekV2[] }) {
  const width = 320;
  const height = 130;
  const left = 8;
  const bottom = 22;
  const top = 16;
  const max = Math.max(1, ...weeks.map((week) => week.sessions));
  const slot = (width - left * 2) / weeks.length;
  const barWidth = slot * 0.62;
  const summary = weeks.map((week) => `${formatWeekLabel(week.week_start)}: ${week.sessions}`).join(", ");
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`} className="analytics-weeks-chart" role="img"
      aria-label={`Тренировок по неделям (12 недель, с понедельника): ${summary}`}
    >
      <line x1={left} x2={width - left} y1={height - bottom} y2={height - bottom} stroke="currentColor" opacity="0.25" />
      {weeks.map((week, index) => {
        const barHeight = week.sessions === 0 ? 0 : Math.max(3, ((height - bottom - top) * week.sessions) / max);
        const x = left + index * slot + (slot - barWidth) / 2;
        return (
          <g key={week.week_start}>
            <rect
              x={x} y={height - bottom - barHeight} width={barWidth} height={barHeight} rx={2}
              fill={SERIES_COLOR} opacity={week.sessions === 0 ? 0.15 : 1}
            />
            {week.sessions > 0 && (
              <text x={x + barWidth / 2} y={height - bottom - barHeight - 3} fontSize="9" textAnchor="middle" fill="currentColor">
                {week.sessions}
              </text>
            )}
            {index % 3 === 0 && (
              <text x={x + barWidth / 2} y={height - 7} fontSize="9" textAnchor="middle" fill="currentColor" opacity="0.7">
                {formatWeekLabel(week.week_start)}
              </text>
            )}
          </g>
        );
      })}
    </svg>
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
  const left = 30;
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
      <text x={left - 4} y={y(max) + 3} fontSize="9" textAnchor="end" fill="currentColor" opacity="0.7">{formatNumber(Math.round(max * 10) / 10)}</text>
      <text x={left - 4} y={y(min) + 3} fontSize="9" textAnchor="end" fill="currentColor" opacity="0.7">{formatNumber(Math.round(min * 10) / 10)}</text>
      <path d={path} fill="none" stroke={SERIES_COLOR} strokeWidth="2" strokeLinejoin="round" />
      {points.map((point, index) => (
        <circle key={`${point.at}-${index}`} cx={x(index)} cy={y(point.y)} r={point.pb ? 4.5 : 2.5} fill={point.pb ? PB_COLOR : SERIES_COLOR} />
      ))}
      <text x={left} y={height - 6} fontSize="9" fill="currentColor" opacity="0.7">{formatShortDate(points[0].at)}</text>
      <text x={width - right} y={height - 6} fontSize="9" textAnchor="end" fill="currentColor" opacity="0.7">
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

/** Аналитика тренировок (TrainingSession v2): активность за 30 дней и 12
 * недель, выбор упражнения, панели по протоколам. Несовместимые протоколы
 * одного упражнения показываются отдельными панелями, никогда не суммируются. */
export function TrainingAnalytics({ initDataRaw }: Props) {
  const [state, setState] = useState<State>({ phase: "loading" });
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const load = useCallback(() => {
    let cancelled = false;
    setState({ phase: "loading" });
    fetchTrainingAnalytics(initDataRaw)
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
  }, [initDataRaw]);

  useEffect(() => load(), [load]);

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
      <div className="analytics-stat-grid analytics-activity-cards">
        <Stat label="Тренировок за 30 дней" value={String(data.activity.sessions_last_30_days)} />
        <Stat label="Активных дней за 30 дней" value={String(data.activity.active_days_last_30_days)} />
      </div>

      <div className="profile-card">
        <p className="section-title">Тренировки по неделям</p>
        <WeeksChart weeks={data.activity.weeks} />
        <p className="hint">Последние 12 недель, неделя — с понедельника.</p>
      </div>

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
