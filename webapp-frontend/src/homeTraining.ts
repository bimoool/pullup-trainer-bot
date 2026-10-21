// Вход в тренировку с Главной: какая тренировка плана «следующая» и можно ли начать её сразу.
// Чистая функция без React/DOM. Правило то же, что у «Начать» на «Планах» (planWeekNav.canStartOccurrence): занятие
// текущей недели, не засчитанное, не «рано» и не под действующим отдыхом K1 — Главная и Планы предлагают одно действие.

import type { PlanItemResponseV2, TrainingPlanResponseV2 } from "./apiV2.ts";
import { canStartOccurrence, restBlockedUntil } from "./planWeekNav.ts";

export type HomeTraining =
  | { kind: "start"; planItemIds: number[]; title: string }
  | { kind: "wait"; availableFrom: string | null }
  | { kind: "none" };

type PlanLike = Pick<TrainingPlanResponseV2, "program_inclusions" | "plan_items" | "current_week_id" | "spacing" | "today">;

export function pickHomeTraining(plan: PlanLike | null, localToday: string): HomeTraining {
  if (plan === null || plan.current_week_id == null) {
    return { kind: "none" };
  }
  const today = plan.today ?? localToday;
  const activeIds = new Set(plan.program_inclusions.filter((i) => i.is_active).map((i) => i.id));
  const candidates: PlanItemResponseV2[] = plan.plan_items
    .filter((item) => (
      item.plan_week_id === plan.current_week_id && !item.legacy_aggregate && item.status !== "removed"
      && item.program_inclusion_id !== null && activeIds.has(item.program_inclusion_id)
      && item.credited_session_id == null && item.occurrence_index != null
    ))
    // «не успеть» — в конец: сначала занятия, которые укладываются в неделю (как nextOccurrenceId на «Планах»).
    .sort((a, b) => (Number(a.state === "infeasible") - Number(b.state === "infeasible"))
      || (a.occurrence_index ?? 0) - (b.occurrence_index ?? 0) || a.id - b.id);
  const startable = candidates.find((item) => (
    (item.state === "available" || item.state === "infeasible")
    && canStartOccurrence(item, restBlockedUntil(item, plan.spacing, today))
  ));
  if (startable !== undefined) {
    const inclusion = plan.program_inclusions.find((i) => i.id === startable.program_inclusion_id);
    return { kind: "start", planItemIds: [startable.id], title: inclusion?.program_name ?? "Тренировка" };
  }
  // Отдых: ближайшая дата, раньше которой сервер не примет старт ни одного занятия группы.
  const dates = candidates
    .map((item) => restBlockedUntil(item, plan.spacing, today) ?? (item.state === "too_early" ? item.available_from ?? null : null))
    .filter((value): value is string => value !== null)
    .sort();
  if (dates.length > 0) {
    return { kind: "wait", availableFrom: dates[0] };
  }
  const waiting = candidates.find((item) => item.state === "too_early" || item.state === "awaiting_assessment");
  return waiting !== undefined ? { kind: "wait", availableFrom: waiting.available_from ?? null } : { kind: "none" };
}

const MONTHS_GEN = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];

/** «2026-10-22» → «22 окт» (без часовых поясов: дата уже календарная, пользовательская). */
export function formatAvailableFrom(iso: string | null): string | null {
  const match = iso === null ? null : /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return match === null ? null : `${Number(match[3])} ${MONTHS_GEN[Number(match[2]) - 1]}`;
}
