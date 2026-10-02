import type { ProtocolType, SessionBlockResponseV2 } from "./apiV2";
import { formatAttempts, formatDuration, formatIntervalsCount, formatNumber } from "./blockFormat";

/** Представление одного блока Журнала v2 (карточка и детали). Значения
 * всегда человекочитаемые: без сырых id, JSON протокола, "8.00 reps" и без
 * выдуманного плана "0:00" из бессмысленных нулевых целей. */
export interface JournalBlockView {
  /** Заголовок блока; null — человекочитаемого имени нет. */
  header: string | null;
  /** Факт одной строкой ("8 · 7", "0:30 · 0:25", "2 попытки · лучший 22"). */
  fact: string;
  /** План, только если он осмысленный (>0); иначе null. */
  plan: string | null;
  protocolLabel: string | null;
  completed: boolean;
}

const PROTOCOL_LABELS: Record<ProtocolType, string> = {
  reps_sets: "Подходы с повторениями",
  time_sets: "Подходы по времени",
  max_effort: "Максимум",
  interval: "Интервалы",
};

interface IntervalResult {
  actual_duration_seconds: number;
  completed_cycles: number;
}

function intervalResultOf(block: SessionBlockResponseV2): IntervalResult | null {
  const result = block.result;
  if (result !== null && typeof result === "object" && (result as { type?: unknown }).type === "interval") {
    return result as unknown as IntervalResult;
  }
  return null;
}

function formatLogValue(unit: string, value: string): string {
  if (unit === "s") {
    return formatDuration(Number(value));
  }
  return formatNumber(value);
}

export function describeJournalBlock(block: SessionBlockResponseV2): JournalBlockView {
  const name = block.exercise_name;
  const logs = block.set_logs;
  const protocolLabel = block.protocol_type !== null ? PROTOCOL_LABELS[block.protocol_type] : null;

  if (block.protocol_type === "interval") {
    const result = intervalResultOf(block);
    const config = block.interval_config;
    return {
      header: name !== null ? `${name} · Интервалы` : "Интервалы",
      fact: result !== null
        ? `${formatDuration(result.actual_duration_seconds)} · ${formatIntervalsCount(result.completed_cycles)}`
        : "Не выполнено",
      plan: config !== null
        ? `${formatDuration(config.total_duration_seconds)} · ${config.work_seconds}/${config.rest_seconds} сек`
        : null,
      protocolLabel,
      completed: result !== null,
    };
  }

  if (block.protocol_type === "max_effort") {
    const isTime = logs.length > 0 && logs[0].unit === "s";
    const kind = isTime ? "Максимум времени" : "Максимум повторений";
    const best = logs.length > 0 ? Math.max(...logs.map((log) => Number(log.value))) : null;
    return {
      header: name !== null ? `${name} · ${kind}` : kind,
      fact: best !== null
        ? `${formatAttempts(logs.length)} · лучший ${isTime ? formatDuration(best) : formatNumber(best)}`
        : "Не выполнено",
      plan: null, // у попыток на максимум цели нет
      protocolLabel,
      completed: logs.length > 0,
    };
  }

  // reps_sets / time_sets и legacy/STEP-блоки без протокола: значения по единице.
  const planned = block.set_targets.filter((target) => Number(target.value) > 0);
  const plan = planned.length > 0
    ? planned.map((target) => formatLogValue(target.unit, target.value)).join(" · ")
    : null;
  return {
    header: name,
    fact: logs.length > 0 ? logs.map((log) => formatLogValue(log.unit, log.value)).join(" · ") : "Не выполнено",
    plan,
    protocolLabel,
    completed: logs.length > 0,
  };
}

/** "03.09.2026, 14:05" — локальное время пользователя. */
export function formatSessionDateTime(isoDateTime: string): string {
  const date = new Date(isoDateTime);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()}, ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** "14:05" — локальное время пользователя (дату несёт заголовок дня в ленте Журнала). */
export function formatSessionTime(isoDateTime: string): string {
  const date = new Date(isoDateTime);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
