import { plural } from "./blockFormat";
import type { WorkoutItemResponseV2 } from "./apiV2";
import { formatSecondsAsMinutesSeconds } from "./timeInput";

/** Человекочитаемые описания карточки «Мои тренировки» на Главной. Только
 * реальные данные Workout: никаких id/JSON/source_type и нулевых целей. */

export function formatExerciseCount(count: number): string {
  return `${count} ${plural(count, "упражнение", "упражнения", "упражнений")}`;
}

const MAX_NAMES = 2;

/** "Подтягивания · Отжимания +1"; пусто — если упражнений нет. */
export function formatExerciseNames(items: WorkoutItemResponseV2[]): string {
  const names = [...items]
    .sort((a, b) => a.order_index - b.order_index)
    .map((item) => item.exercise_name)
    .filter((name) => name.trim() !== "");
  if (names.length === 0) {
    return "";
  }
  const head = names.slice(0, MAX_NAMES).join(" · ");
  return names.length > MAX_NAMES ? `${head} +${names.length - MAX_NAMES}` : head;
}

function positive(value: unknown): number | null {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
}

/** Краткая цель первого упражнения ("3 × 8", "2 × 0:30", "Интервалы · 3:00");
 * null, если цели нет или она нулевая — тогда строку не показываем. */
export function formatFirstProtocol(items: WorkoutItemResponseV2[]): string | null {
  const first = [...items].sort((a, b) => a.order_index - b.order_index)[0];
  if (!first) {
    return null;
  }
  const protocol = first.protocol;
  const prescription = (protocol.prescription ?? {}) as Record<string, unknown>;
  const sets = positive(prescription.sets);
  switch (protocol.type) {
    case "reps_sets": {
      const reps = positive(prescription.reps);
      return sets && reps ? `${sets} × ${reps}` : null;
    }
    case "time_sets": {
      const duration = positive(prescription.duration_seconds);
      return sets && duration ? `${sets} × ${formatSecondsAsMinutesSeconds(duration)}` : null;
    }
    case "max_effort": {
      const attempts = positive(prescription.attempts);
      return attempts ? `Максимум · ${attempts} ${plural(attempts, "попытка", "попытки", "попыток")}` : null;
    }
    case "interval": {
      const total = positive(protocol.total_duration_seconds);
      return total ? `Интервалы · ${formatSecondsAsMinutesSeconds(total)}` : null;
    }
    default:
      return null;
  }
}
