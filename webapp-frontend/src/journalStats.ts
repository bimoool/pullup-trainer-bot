import type { SessionResponseV2 } from "./apiV2";
import { formatDuration } from "./blockFormat.ts";
import { formatDurationHm } from "./journalLog.ts";

/** Сетка из трёх подписанных показателей на карточке Журнала (#286, референс Crimpd: «Intensity / Completion / …»).
 * Чистая агрегация по всей записи: у многоблочной сессии показываются суммы, а факты по блокам остаются в деталях. */
export type JournalStatKey = "sets" | "reps" | "time" | "intervals" | "duration" | "distance" | "effort";

export interface JournalStat {
  key: JournalStatKey;
  label: string;
  /** Готовая строка; «—» — данных нет. */
  value: string;
  /** Для key="effort" — число 1..5 (цвет по effortScale), иначе null. */
  effort: number | null;
}

export const NO_VALUE = "—";

type StatSession = Pick<SessionResponseV2, "blocks" | "effort"> & {
  activity_type?: string | null;
  duration_seconds?: number | null;
};

interface Totals {
  sets: number;
  reps: number;
  hasReps: boolean;
  seconds: number;
  hasSeconds: boolean;
  cycles: number;
  intervalSeconds: number;
  hasIntervals: boolean;
}

function totalsOf(blocks: StatSession["blocks"]): Totals {
  const totals: Totals = {
    sets: 0, reps: 0, hasReps: false, seconds: 0, hasSeconds: false, cycles: 0, intervalSeconds: 0, hasIntervals: false,
  };
  for (const block of blocks) {
    for (const log of block.set_logs) {
      const value = Number(log.value);
      if (!Number.isFinite(value)) {
        continue;
      }
      totals.sets += 1;
      if (log.unit === "s") {
        totals.seconds += value;
        totals.hasSeconds = true;
      } else {
        totals.reps += value;
        totals.hasReps = true;
      }
    }
    const result = block.result as { type?: unknown; actual_duration_seconds?: unknown; completed_cycles?: unknown } | null;
    if (block.protocol_type === "interval" && result !== null && typeof result === "object" && result.type === "interval") {
      totals.hasIntervals = true;
      totals.cycles += Number(result.completed_cycles) || 0;
      totals.intervalSeconds += Number(result.actual_duration_seconds) || 0;
    }
  }
  return totals;
}

function effortStat(effort: string | number | null | undefined): JournalStat {
  if (effort === null || effort === undefined || effort === "" || !Number.isFinite(Number(effort))) {
    return { key: "effort", label: "Усилие", value: NO_VALUE, effort: null };
  }
  const numeric = Number(effort);
  return { key: "effort", label: "Усилие", value: String(numeric), effort: numeric };
}

/** Три показателя карточки: силовая/по плану — Подходы · Повторы (или Время) · Усилие;
 * интервальная — Интервалы · Время · Усилие; активность — Длительность · Дистанция («—», в данных её нет) · Усилие. */
export function journalCardStats(session: StatSession): [JournalStat, JournalStat, JournalStat] {
  const effort = effortStat(session.effort);
  if (session.activity_type != null) {
    return [
      {
        key: "duration", label: "Длительность", effort: null,
        value: session.duration_seconds != null ? formatDurationHm(session.duration_seconds) : NO_VALUE,
      },
      { key: "distance", label: "Дистанция", value: NO_VALUE, effort: null },
      effort,
    ];
  }
  const totals = totalsOf(session.blocks);
  if (totals.sets === 0 && totals.hasIntervals) {
    return [
      { key: "intervals", label: "Интервалы", value: String(totals.cycles), effort: null },
      { key: "time", label: "Время", value: formatDuration(totals.intervalSeconds), effort: null },
      effort,
    ];
  }
  const sets: JournalStat = {
    key: "sets", label: "Подходы", value: totals.sets > 0 ? String(totals.sets) : NO_VALUE, effort: null,
  };
  if (!totals.hasReps && totals.hasSeconds) {
    return [sets, { key: "time", label: "Время", value: formatDuration(totals.seconds), effort: null }, effort];
  }
  return [
    sets,
    { key: "reps", label: "Повторы", value: totals.hasReps ? String(Math.round(totals.reps * 100) / 100) : NO_VALUE, effort: null },
    effort,
  ];
}
