import type { WorkoutItemResponseV2 } from "./apiV2";
import { draftFromProtocol, humanDuration, plural, previewLines, type ProtocolFormValue } from "./protocolConfig.ts";

/** Чистые форматтеры экрана Workout Detail. Всё берётся только из сохранённых
 * полей протокола; нет данных — нет и оценки (никаких догадок). */

/** «3 × 8 повторений · отдых 1:00» — тот же previewLines, что в редакторе. */
export function formatItemSummary(protocol: ProtocolFormValue): string {
  const draft = draftFromProtocol(protocol);
  const [main, detail] = previewLines(draft);
  if (draft.kind === "interval") {
    return `${main} · ${detail}`;
  }
  const rest = draft.kind === "max_effort" ? draft.maxRestSeconds : draft.restSeconds;
  return rest > 0 ? `${main} · отдых ${humanDuration(rest)}` : main;
}

function positive(value: unknown): number | null {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
}

function nonNegative(value: unknown): number | null {
  if (value === undefined || value === null) {
    return 0;
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric >= 0 ? numeric : null;
}

/** Секунды одного упражнения или null, если по сохранённым полям их не посчитать:
 * у повторений и попыток длительности в протоколе нет. */
export function estimateItemSeconds(protocol: ProtocolFormValue): number | null {
  if (protocol.type === "interval") {
    return positive(protocol.total_duration_seconds);
  }
  if (protocol.type === "time_sets") {
    const prescription = (protocol.prescription ?? {}) as Record<string, unknown>;
    const sets = positive(prescription.sets);
    const duration = positive(prescription.duration_seconds);
    const rest = nonNegative(protocol.rest_seconds);
    if (!sets || !duration || rest === null) {
      return null;
    }
    return sets * duration + (sets - 1) * rest;
  }
  return null;
}

/** Оценка всей тренировки в секундах; null, если хоть у одного упражнения данных нет. */
export function estimateWorkoutSeconds(items: WorkoutItemResponseV2[]): number | null {
  if (items.length === 0) {
    return null;
  }
  let total = 0;
  for (const item of items) {
    const seconds = estimateItemSeconds(item.protocol);
    if (seconds === null) {
      return null;
    }
    total += seconds;
  }
  return total;
}

/** «≈ 12 мин» (округление вверх до минуты); null → строку не показываем. */
export function formatEstimate(seconds: number | null): string | null {
  if (seconds === null || seconds <= 0) {
    return null;
  }
  const minutes = Math.ceil(seconds / 60);
  return `≈ ${minutes} мин`;
}

/** «3 подхода» для короткого результата в истории. */
export function formatSetsDone(count: number): string {
  return `${count} ${plural(count, "подход", "подхода", "подходов")}`;
}
