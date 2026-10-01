/** Шкала усилия 1–5 (Crimpd «How hard was this set?»): хранимые значения
 * остаются "1".."5", слова — только подпись. Одна шкала для подхода и для
 * тренировки целиком. */
export const EFFORT_SCALE: { value: string; label: string }[] = [
  { value: "1", label: "Очень легко" },
  { value: "2", label: "Легко" },
  { value: "3", label: "Средне" },
  { value: "4", label: "Тяжело" },
  { value: "5", label: "Предел" },
];

export const SET_EFFORT_PROMPT = "Насколько тяжело было?";
export const WORKOUT_EFFORT_PROMPT = "Как прошла тренировка?";
export const WORKOUT_COMMENT_MAX = 1000;

/** «3 Средне» для известного значения; для неизвестного/дробного — как есть. */
export function effortWithWord(value: string | number | null | undefined): string | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const normalized = String(Number(value));
  const found = EFFORT_SCALE.find((option) => option.value === normalized);
  return found ? `${found.value} ${found.label}` : String(value);
}

/** Тело review-шага для /complete: пустое → null, заметка обрезается по лимиту. */
export function reviewPayload(
  effort: string | null, comment: string,
): { effort: string | null; comment: string | null } {
  const trimmed = comment.trim().slice(0, WORKOUT_COMMENT_MAX);
  return { effort, comment: trimmed === "" ? null : trimmed };
}
