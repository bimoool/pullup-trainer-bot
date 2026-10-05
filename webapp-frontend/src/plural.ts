/** Русское склонение по числу: plural(1, "тренировка", "тренировки", "тренировок").
 * 1 → one, 2–4 → few, 0/5–20 → many, 21 → one, 22–24 → few, 11–14 → many (в любой сотне). */
export function plural(count: number, one: string, few: string, many: string): string {
  const mod100 = Math.abs(Math.trunc(count)) % 100;
  const mod10 = mod100 % 10;
  if (mod100 >= 11 && mod100 <= 14) {
    return many;
  }
  if (mod10 === 1) {
    return one;
  }
  if (mod10 >= 2 && mod10 <= 4) {
    return few;
  }
  return many;
}

/** «5 тренировок» — число + склонённая форма. */
export function countNoun(count: number, one: string, few: string, many: string): string {
  return `${count} ${plural(count, one, few, many)}`;
}
