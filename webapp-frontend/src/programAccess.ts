/** Нужна ли Premium для тренировок программы (app/domain/program_access.py). Нет поля — считать "premium". */
export type ProgramAccessLevel = "free" | "premium";

type PlanLike = {
  program_inclusions: { id: number; is_active: boolean; access_level?: ProgramAccessLevel }[];
  plan_items: { id: number; program_inclusion_id: number | null }[];
};

/** Подсказка предэкрану: стартуемые строки требуют подписки (истина — 402 на старте). Решение 2026-10-17: строка
 * без программы (своя/ручная/свой план) — доп. тренировка, Premium; строка платной программы — Premium; бесплатна
 * только «Подтягивания». Если ни одной курсовой инклюзии определить не удалось — консервативно true. */
export function courseRequiresPremium(plan: PlanLike | null, planItemIds: number[] | undefined): boolean {
  if (plan === null) {
    return true;
  }
  const wanted = planItemIds !== undefined && planItemIds.length > 0 ? new Set(planItemIds) : null;
  if (wanted !== null && plan.plan_items.some((item) => wanted.has(item.id) && item.program_inclusion_id === null)) {
    return true;
  }
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
