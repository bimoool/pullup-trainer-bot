/** Чистые хелперы блока «Сравнение с похожими» (#276): тексты и форматирование агрегатов. */

export const PEER_TITLE = "Сравнение с похожими";
export const PEER_INSUFFICIENT_TEXT = "Пока мало данных для сравнения (нужно ≥20 человек)";
export const PEER_NO_RESULT_TEXT = "Запишите результат, чтобы сравнить себя с похожими.";

export type PeerCohort = { level: string; label: string; size_bucket: string };
export type PeerNextTarget = { percentile: number; value: string };
export type PeerInsights = {
  status: "ok" | "insufficient" | "no_result" | string;
  min_cohort_size: number;
  unit: string;
  own_value: string | null;
  cohort: PeerCohort | null;
  percentile: number | null;
  median: string | null;
  next_target: PeerNextTarget | null;
};

/** Вид блока по ответу: `ok` показывает числа только при полном наборе агрегатов. */
export function peerView(data: PeerInsights): "ok" | "insufficient" | "no_result" {
  if (data.status === "no_result") {
    return "no_result";
  }
  if (data.status === "ok" && data.cohort !== null && data.percentile !== null && data.median !== null) {
    return "ok";
  }
  return "insufficient";
}

function withUnit(value: string, unit: string): string {
  return unit ? `${value} ${unit}` : value;
}

/** «Мужчины 30–39 лет · 20–49 человек». */
export function formatPeerCohort(cohort: PeerCohort): string {
  return `${cohort.label} · ${cohort.size_bucket} человек`;
}

/** Процентиль — доля когорты, которую результат обходит: «Лучше, чем у 73% похожих». */
export function formatPeerPercentile(percentile: number): string {
  return `Лучше, чем у ${percentile}% похожих`;
}

export function formatPeerMedian(median: string, unit: string): string {
  return `Медиана: ${withUnit(median, unit)}`;
}

/** Следующий ориентир; повторения целые — порог вида 15.25 повт. округляем вверх до 16. */
export function formatPeerNext(target: PeerNextTarget, unit: string, integerOnly: boolean): string {
  const value = integerOnly ? String(Math.ceil(Number(target.value))) : target.value;
  return `Следующий ориентир: ${withUnit(value, unit)} — лучше, чем у ${target.percentile}% похожих`;
}

/** Ширина полосы 0–100 для индикатора процентиля; вне диапазона и NaN зажимаются. */
export function peerBarWidth(percentile: number): number {
  return Number.isFinite(percentile) ? Math.max(0, Math.min(100, Math.round(percentile))) : 0;
}
