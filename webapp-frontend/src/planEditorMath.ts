// UX-EDITOR — чистые помощники редактора плана и расписания (без React; покрыты tests/planEditorMath.test.ts).

import type { EditorWeekV2, ScheduleWorkoutV2 } from "./apiV2";

export const WEEK_MAX_TOTAL = 14;

/** Итоги по неделям — сумма количеств всех тренировок недели. */
export function weekTotals(weeks: { quantities: Record<string, number> }[]): number[] {
  return weeks.map((week) => Object.values(week.quantities).reduce((sum, count) => sum + count, 0));
}

/** Можно ли изменить количество: границы — выполненное (снизу) и недельный максимум (сверху). */
export function quantityBounds(week: EditorWeekV2, workoutId: number): { min: number; canInc: boolean; canDec: boolean } {
  const key = String(workoutId);
  const value = week.quantities[key] ?? 0;
  const min = week.done[key] ?? 0;
  const editable = week.state !== "past";
  return { min, canInc: editable && week.total < WEEK_MAX_TOTAL, canDec: editable && value > min };
}

/** «осталось разместить N» / «все занятия размещены». */
export function remainingLabel(remaining: number): string {
  return remaining > 0 ? `осталось разместить ${remaining}` : "все занятия размещены";
}

/** Итог по дню (для строки «всего в день») — берётся с сервера; здесь только пересчёт из раскладки. */
export function dayTotals(workouts: Pick<ScheduleWorkoutV2, "placed_by_day">[]): number[] {
  return Array.from({ length: 7 }, (_, day) => workouts.reduce((sum, w) => sum + (w.placed_by_day[day] ?? 0), 0));
}

export const PHASE_LABELS: Record<string, string> = { base: "База", rest: "Отдых", peak: "Пик" };
export const PHASE_ORDER = ["base", "rest", "peak"] as const;

export function nextPhase(phase: string): "base" | "rest" | "peak" {
  const index = PHASE_ORDER.indexOf(phase as (typeof PHASE_ORDER)[number]);
  return PHASE_ORDER[(index + 1) % PHASE_ORDER.length];
}

/** Подпись недели с нулевым итогом (UX-12). */
export function weekEmptyNote(total: number): string | null {
  return total === 0 ? "Неделя отдыха по плану" : null;
}
