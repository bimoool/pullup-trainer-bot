import {
  addWorkoutItem, createPlanItem, createWorkout, deleteWorkout, removePlanItem, type PlanItemResponseV2,
} from "./apiV2";
import type { ProtocolFormValue } from "./protocolConfig";

/**
 * Аудит staging 7500c37: строка плана «только упражнение» (PlanItem.exercise_id без тренировки) не хранит ни
 * подходов, ни повторений — в схеме нет поля для протокола, и старт подставлял заглушку «3 подхода с целью 0»
 * (`LiveSessionService._resolve_plain_exercise_block`), которую Live показывал как «Максимум · 3 попытки».
 *
 * Без миграции (решение владельца): выбранные пользователем параметры сохраняются в уже существующей модели —
 * своя тренировка из одного упражнения (Workout + WorkoutItem с протоколом), в план встаёт она (complex_id).
 * Если план не принял строку, только что созданная тренировка мягко удаляется (как «Удалить тренировку»),
 * чтобы в «Моих тренировках» не оставался осиротевший черновик.
 */
export async function addExerciseWithProtocolToPlan(
  initDataRaw: string,
  args: {
    exerciseId: number; exerciseName: string; protocol: ProtocolFormValue;
    planWeekId: number | null; dayOfWeek: number | null;
  },
): Promise<PlanItemResponseV2> {
  const workout = await createWorkout(initDataRaw, args.exerciseName);
  try {
    await addWorkoutItem(initDataRaw, workout.id, args.exerciseId, args.protocol);
    return await createPlanItem(initDataRaw, {
      complex_id: workout.id,
      // #297: без недели поле не шлём — сервер сам привяжет строку к текущей неделе.
      ...(args.planWeekId !== null ? { plan_week_id: args.planWeekId } : {}),
      day_of_week: args.dayOfWeek,
      count_per_week: 1,
    });
  } catch (error) {
    await deleteWorkout(initDataRaw, workout.id).catch(() => undefined);
    throw error;
  }
}

/** Строка плана, для которой не задано, как выполнять упражнение (старые «только упражнение» строки). */
export function isExerciseOnlyPlanItem(item: Pick<PlanItemResponseV2, "complex_id" | "program_inclusion_id">): boolean {
  return item.complex_id === null && item.program_inclusion_id === null;
}

/**
 * Старая строка «только упражнение» → та же строка с заданными параметрами: новая строка (своя тренировка из
 * одного упражнения) на тот же день и неделю, старая убирается из плана. Убрать старую не удалось (например, уже
 * засчитана) — новая всё равно остаётся: пользователь тренируется по выбранным параметрам, а не по заглушке.
 */
export async function replaceExerciseOnlyPlanItem(
  initDataRaw: string,
  item: Pick<PlanItemResponseV2, "id" | "exercise_id" | "plan_week_id" | "day_of_week">,
  exerciseName: string,
  protocol: ProtocolFormValue,
): Promise<PlanItemResponseV2> {
  const created = await addExerciseWithProtocolToPlan(initDataRaw, {
    exerciseId: item.exercise_id, exerciseName, protocol, planWeekId: item.plan_week_id, dayOfWeek: item.day_of_week,
  });
  await removePlanItem(initDataRaw, item.id).catch(() => undefined);
  return created;
}
