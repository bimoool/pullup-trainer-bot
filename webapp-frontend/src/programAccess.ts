/** Нужна ли Premium для тренировок программы (app/domain/program_access.py). Нет поля — считать "premium". */
export type ProgramAccessLevel = "free" | "premium";

type PlanLike = {
  program_inclusions: { id: number; is_active: boolean; access_level?: ProgramAccessLevel }[];
  plan_items: { id: number; program_inclusion_id: number | null }[];
};

/** Подсказка предэкрану: стартуемые строки курса относятся к платной программе (истина — 402 на старте). Строки без
 * курса не в счёт; если ни одной курсовой инклюзии определить не удалось — консервативно true (прежнее поведение). */
export function courseRequiresPremium(plan: PlanLike | null, planItemIds: number[] | undefined): boolean {
  if (plan === null) {
    return true;
  }
  const wanted = planItemIds !== undefined && planItemIds.length > 0 ? new Set(planItemIds) : null;
  const inclusionIds = new Set(
    wanted === null
      ? plan.program_inclusions.filter((inclusion) => inclusion.is_active).map((inclusion) => inclusion.id)
      : plan.plan_items
          .filter((item) => wanted.has(item.id) && item.program_inclusion_id !== null)
          .map((item) => item.program_inclusion_id as number),
  );
  const inclusions = plan.program_inclusions.filter((inclusion) => inclusionIds.has(inclusion.id));
  if (inclusions.length === 0) {
    return true;
  }
  return inclusions.some((inclusion) => inclusion.access_level !== "free");
}
