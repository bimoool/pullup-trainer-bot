import type { IntervalConfigResponse, LiveSetTargetResponse, ProtocolType } from "./apiV2";

/** Человекочитаемые описания блоков тренировки (R1: interstitial, Live,
 * Summary; тот же модуль переиспользует Журнал). Никаких сырых id/JSON/
 * "8.00 reps" — только то, что пользователь понимает. */

export function formatDuration(totalSeconds: number): string {
  const clamped = Math.max(0, Math.round(totalSeconds));
  const minutes = Math.floor(clamped / 60);
  const seconds = clamped % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/** m:ss до часа, h:mm:ss от часа — суммарное время в работе. */
export function formatLongDuration(totalSeconds: number): string {
  const clamped = Math.max(0, Math.round(totalSeconds));
  if (clamped < 3600) {
    return formatDuration(clamped);
  }
  const hours = Math.floor(clamped / 3600);
  const rest = clamped % 3600;
  return `${hours}:${String(Math.floor(rest / 60)).padStart(2, "0")}:${String(rest % 60).padStart(2, "0")}`;
}

/** "8.00" -> "8"; "22.5" -> "22.5". */
export function formatNumber(value: string | number): string {
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) {
    return String(value);
  }
  return String(numeric);
}

export function plural(count: number, one: string, few: string, many: string): string {
  const mod100 = count % 100;
  const mod10 = count % 10;
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

export function formatAttempts(count: number): string {
  return `${count} ${plural(count, "попытка", "попытки", "попыток")}`;
}

export function formatIntervalsCount(count: number): string {
  return `${count} ${plural(count, "интервал", "интервала", "интервалов")}`;
}

function formatSecondsShort(seconds: number): string {
  return seconds < 60 ? `${seconds} сек` : formatDuration(seconds);
}

/** Цель подхода: "8 повт." / "0:30" / null, если цели нет (0 — не план). */
export function formatTarget(target: LiveSetTargetResponse): string | null {
  const value = Number(target.value);
  if (!(value > 0)) {
    return null;
  }
  if (target.unit === "s") {
    return formatDuration(value);
  }
  if (target.unit === "reps") {
    return `${formatNumber(value)} повт.`;
  }
  return `${formatNumber(value)} ${target.unit}`;
}

/** "2×30 сек" / "3×8" / "Максимум · 2 попытки" / "3:00 · 10/20 сек". */
export function describeBlockPlan(
  protocolType: ProtocolType | null,
  targets: LiveSetTargetResponse[],
  intervalConfig: IntervalConfigResponse | null,
): string | null {
  if (protocolType === "interval" && intervalConfig !== null) {
    return `${formatDuration(intervalConfig.total_duration_seconds)} · ${intervalConfig.work_seconds}/${intervalConfig.rest_seconds} сек`;
  }
  if (protocolType === "max_effort") {
    return `Максимум · ${formatAttempts(targets.length)}`;
  }
  if (targets.length === 0) {
    return null;
  }
  const values = targets.map((target) => Number(target.value));
  const allSame = values.every((value) => value === values[0]);
  if (!(values[0] > 0)) {
    return `${targets.length} ${plural(targets.length, "подход", "подхода", "подходов")}`;
  }
  const unit = targets[0].unit;
  if (allSame) {
    const one = unit === "s" ? formatSecondsShort(values[0]) : formatNumber(values[0]);
    return `${targets.length}×${one}`;
  }
  return values.map((value) => (unit === "s" ? formatSecondsShort(value) : formatNumber(value))).join(" · ");
}

/** Подпись поля результата в живой сессии и подсказка с целью подхода.
 * «Результат» — только запасной вариант для неизвестной единицы; у max-блока
 * цели-подсказки нет (не выдумываем). */
export function resultInputLabel(
  protocolType: ProtocolType | null,
  target: LiveSetTargetResponse | null,
): { label: string; hint: string | null } {
  const planText = target !== null ? formatTarget(target) : null;
  const hint = planText !== null ? `Цель: ${planText}` : null;
  if (protocolType === "max_effort") {
    return { label: "Повторений", hint: null };
  }
  if (protocolType === "time_sets" || target?.unit === "s") {
    return { label: "Секунды", hint };
  }
  if (target?.unit === "reps") {
    return { label: "Повторений", hint };
  }
  return { label: "Результат", hint };
}
