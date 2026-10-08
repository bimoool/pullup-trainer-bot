import type { WorkoutItemResponseV2, WorkoutResponseV2 } from "./apiV2";

/** Ключ блока v2, построенного из V1-строки complex_items: `i<item.id>e<item.exercise_id>` —
 * тот же, что у бэкенда (app/domain/workout_definition.py::v1_block_key, WORKOUT_DOMAIN_V2 §9.5).
 * Упражнение — часть ключа: строка, сменившая упражнение, — другой блок. */
export function v1BlockKey(item: Pick<WorkoutItemResponseV2, "id" | "exercise_id">): string {
  return `i${item.id}e${item.exercise_id}`;
}

/** Текст рецепта из канонической версии v2 (issue #303, WORKOUT_DOMAIN_V2 §7): сервер считает
 * его одной функцией describe() для всех экранов — Detail, карточек, пре-скрина. Клиент рецепт
 * не выводит заново («17 × 3» вместо W-лесенки — ровно такой пересчёт). null — у тренировки нет
 * v2-версии (или блока этой строки), экран показывает прежнюю V1-сводку. */
export function itemPrescriptionLine(
  workout: Pick<WorkoutResponseV2, "prescription">,
  item: Pick<WorkoutItemResponseV2, "id" | "exercise_id">,
): string | null {
  const key = v1BlockKey(item);
  const block = workout.prescription?.find((candidate) => candidate.key === key);
  if (!block) {
    return null;
  }
  return block.rest_description ? `${block.description} · ${block.rest_description}` : block.description;
}

/** Короткая цель первого блока для карточки («5-4-3-2-1-…», «Максимум × 4») или null. */
export function firstPrescriptionDescription(workout: Pick<WorkoutResponseV2, "prescription">): string | null {
  return workout.prescription?.[0]?.description ?? null;
}
