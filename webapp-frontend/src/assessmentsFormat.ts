/** Чистые хелперы хаба «Тесты» (#260): форматирование и геометрия графика. */

export const NOT_TESTED_TEXT = "Ещё не проходили";
export const NOT_IN_PROGRESSION_NOTE = "Результаты тестов не влияют на прогрессию и стартовый замер.";

/** «2026-09-03» -> «03.09.2026». */
export function formatIsoDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-");
  return `${day}.${month}.${year}`;
}

/** «12 повт.», «42.5 сек». Единица приходит с бэкенда. */
export function formatValue(value: string, unit: string): string {
  return unit ? `${value} ${unit}` : value;
}

/** Строка карточки: «12 повт. · 03.09.2026» или «Ещё не проходили». */
export function formatLastResult(last: { value: string; unit: string; performed_on: string } | null): string {
  return last ? `${formatValue(last.value, last.unit)} · ${formatIsoDate(last.performed_on)}` : NOT_TESTED_TEXT;
}

export type FormInput = { performedOn: string; value: string; note: string };
export type FormValid = { ok: true; performedOn: string; value: number; note: string | null };
export type FormInvalid = { ok: false; error: string };

/** Проверка формы «Записать результат»; ошибка — короткий текст для UI. */
export function validateResultForm(input: FormInput, today: string, integerOnly: boolean): FormValid | FormInvalid {
  if (!input.performedOn) {
    return { ok: false, error: "Укажите дату" };
  }
  if (input.performedOn > today) {
    return { ok: false, error: "Дата не может быть в будущем" };
  }
  const normalized = input.value.trim().replace(",", ".");
  const value = Number(normalized);
  if (normalized === "" || !Number.isFinite(value) || value <= 0) {
    return { ok: false, error: "Введите значение больше нуля" };
  }
  if (value > 9999) {
    return { ok: false, error: "Слишком большое значение" };
  }
  if (integerOnly && !Number.isInteger(value)) {
    return { ok: false, error: "Повторения — целое число" };
  }
  if (!/^\d+(\.\d{1,2})?$/.test(normalized)) {
    return { ok: false, error: "Не больше двух знаков после запятой" };
  }
  const note = input.note.trim();
  if (note.length > 500) {
    return { ok: false, error: "Заметка не длиннее 500 символов" };
  }
  return { ok: true, performedOn: input.performedOn, value, note: note === "" ? null : note };
}

export type ChartPoint = { x: number; y: number };

/** Точки линии в рамке width×height с отступом pad; значения — по порядку (старые → новые).
 * Одна точка — по центру; одинаковые значения — горизонтальная линия по центру. */
export function chartPoints(values: number[], width: number, height: number, pad: number): ChartPoint[] {
  if (values.length === 0) {
    return [];
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  const innerW = width - 2 * pad;
  const innerH = height - 2 * pad;
  return values.map((value, index) => ({
    x: values.length === 1 ? width / 2 : pad + (index * innerW) / (values.length - 1),
    y: span === 0 ? height / 2 : pad + (1 - (value - min) / span) * innerH,
  }));
}

export function pathFor(points: ChartPoint[]): string {
  return points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
}

/** Лучший результат — максимум (для всех стартовых протоколов больше = лучше). */
export function bestValue(values: number[]): number | null {
  return values.length === 0 ? null : Math.max(...values);
}
