// issue #304 (PROGRAM_PLAN_V2 §7) — разбор объёма своего плана по неделям: «2 2 0 2 2 0».
// 0 — валидная пустая неделя; день недели — подсказка, к объёму отношения не имеет.

export const CUSTOM_WEEK_MAX_COUNT = 14;
export const CUSTOM_PLAN_MAX_WEEKS = 52;

export function parseWeekVolumes(text: string): { weeks: number[]; error: string | null } {
  const tokens = text.split(/[\s,;/]+/).filter((token) => token.length > 0);
  if (tokens.length === 0) {
    return { weeks: [], error: "Укажите число тренировок хотя бы для одной недели" };
  }
  if (tokens.length > CUSTOM_PLAN_MAX_WEEKS) {
    return { weeks: [], error: `Не больше ${CUSTOM_PLAN_MAX_WEEKS} недель` };
  }
  const weeks: number[] = [];
  for (const token of tokens) {
    if (!/^\d+$/.test(token)) {
      return { weeks: [], error: `«${token}» — не число` };
    }
    const value = Number(token);
    if (value > CUSTOM_WEEK_MAX_COUNT) {
      return { weeks: [], error: `Тренировок в неделю: от 0 до ${CUSTOM_WEEK_MAX_COUNT}` };
    }
    weeks.push(value);
  }
  if (!weeks.some((count) => count > 0)) {
    return { weeks: [], error: "Хотя бы в одной неделе должна быть тренировка" };
  }
  return { weeks, error: null };
}
