import type { WorkoutResponseV2 } from "./apiV2";

/** Текст рецепта из канонической версии v2 (issue #303, WORKOUT_DOMAIN_V2 §7): сервер считает
 * его одной функцией describe() для всех экранов — Detail, карточек, пре-скрина. Клиент рецепт
 * не выводит заново («17 × 3» вместо W-лесенки — ровно такой пересчёт). null — у тренировки нет
 * v2-версии, экран показывает прежнюю V1-сводку. Ключ блока V1-головы — `i<item.id>`. */
export function itemPrescriptionLine(
  workout: Pick<WorkoutResponseV2, "prescription">,
  itemId: number,
): string | null {
  const block = workout.prescription?.find((candidate) => candidate.key === `i${itemId}`);
  if (!block) {
    return null;
  }
  return block.rest_description ? `${block.description} · ${block.rest_description}` : block.description;
}

/** Короткая цель первого блока для карточки («5-4-3-2-1-…», «Максимум × 4») или null. */
export function firstPrescriptionDescription(workout: Pick<WorkoutResponseV2, "prescription">): string | null {
  return workout.prescription?.[0]?.description ?? null;
}
