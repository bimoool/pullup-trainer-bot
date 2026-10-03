// Единицы отображения (#268): хранение всегда метрическое (кг/см), здесь только
// перевод для показа и ввода. Чистые функции — без React и без обращения к окружению.

export type WeightUnit = "kg" | "lb";
export type HeightUnit = "cm" | "in";

const KG_PER_LB = 0.45359237;
const CM_PER_IN = 2.54;

export const WEIGHT_UNIT_LABEL: Record<WeightUnit, string> = { kg: "кг", lb: "фунт." };
export const HEIGHT_UNIT_LABEL: Record<HeightUnit, string> = { cm: "см", in: "дюйм." };

function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

/** Число без хвостовых нулей: 80 → "80", 80.5 → "80.5". */
function trim(value: number): string {
  return String(round1(value));
}

export function kgToUnit(kg: number, unit: WeightUnit): number {
  return unit === "lb" ? round1(kg / KG_PER_LB) : round1(kg);
}

export function unitToKg(value: number, unit: WeightUnit): number {
  return unit === "lb" ? Math.round(value * KG_PER_LB * 100) / 100 : value;
}

export function cmToUnit(cm: number, unit: HeightUnit): number {
  return unit === "in" ? round1(cm / CM_PER_IN) : cm;
}

export function unitToCm(value: number, unit: HeightUnit): number {
  return unit === "in" ? Math.round(value * CM_PER_IN) : Math.round(value);
}

/** «80.5 кг» / «177.5 фунт.»; null → «не указано». */
export function formatWeight(kg: string | number | null, unit: WeightUnit): string {
  if (kg === null || kg === "") {
    return "не указано";
  }
  return `${trim(kgToUnit(Number(kg), unit))} ${WEIGHT_UNIT_LABEL[unit]}`;
}

export function formatHeight(cm: number | null, unit: HeightUnit): string {
  if (cm === null) {
    return "не указано";
  }
  return `${trim(cmToUnit(cm, unit))} ${HEIGHT_UNIT_LABEL[unit]}`;
}

/** Текст поля ввода при смене единицы (пустое остаётся пустым, мусор не трогаем). */
export function convertWeightText(text: string, from: WeightUnit, to: WeightUnit): string {
  const value = Number(text.trim().replace(",", "."));
  if (text.trim() === "" || !Number.isFinite(value)) {
    return text;
  }
  // Та же единица: только нормализуем запись («75.00» → «75»), без потери точности.
  return from === to ? String(value) : trim(kgToUnit(unitToKg(value, from), to));
}

export function convertHeightText(text: string, from: HeightUnit, to: HeightUnit): string {
  const value = Number(text.trim().replace(",", "."));
  if (text.trim() === "" || !Number.isFinite(value) || from === to) {
    return text;
  }
  return trim(cmToUnit(unitToCm(value, from), to));
}
