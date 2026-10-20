// Вход в тренировку с Главной: какая тренировка плана «следующая» и можно ли начать её сразу.
// Чистая функция без React/DOM. Правило то же, что у «Начать» на «Планах»: занятие текущей недели,
// не засчитанное, в состоянии «available» (сервер уже учёл разнос тренировок и ожидание замера).

import type { PlanItemResponseV2, TrainingPlanResponseV2 } from "./apiV2";

export type HomeTraining =
  | { kind: "start"; planItemIds: number[]; title: string }
  | { kind: "wait"; availableFrom: string | null }
  | { kind: "none" };

type PlanLike = Pick<TrainingPlanResponseV2, "program_inclusions" | "plan_items" | "current_week_id">;

export function pickHomeTraining(plan: PlanLike | null): HomeTraining {
  if (plan === null || plan.current_week_id == null) {
    return { kind: "none" };
  }
  const activeIds = new Set(plan.program_inclusions.filter((i) => i.is_active).map((i) => i.id));
  const candidates: PlanItemResponseV2[] = plan.plan_items
    .filter((item) => (
      item.plan_week_id === plan.current_week_id && !item.legacy_aggregate && item.status !== "removed"
      && item.program_inclusion_id !== null && activeIds.has(item.program_inclusion_id)
      && item.credited_session_id == null && item.occurrence_index != null
    ))
    .sort((a, b) => (a.occurrence_index ?? 0) - (b.occurrence_index ?? 0) || a.id - b.id);
  const next = candidates.find((item) => item.state === "available");
  if (next !== undefined) {
    const inclusion = plan.program_inclusions.find((i) => i.id === next.program_inclusion_id);
    return { kind: "start", planItemIds: [next.id], title: inclusion?.program_name ?? "Тренировка" };
  }
  const waiting = candidates.find((item) => item.state === "too_early" || item.state === "awaiting_assessment");
  return waiting !== undefined ? { kind: "wait", availableFrom: waiting.available_from ?? null } : { kind: "none" };
}
