import type { SessionResponseV2 } from "./apiV2";

/**
 * Слияние догруженной страницы Журнала (#289 R-3). `startedEpoch` — эпоха списка в момент
 * запроса «Показать ещё», `currentEpoch` — в момент ответа. Эпоха растёт при каждой
 * перезагрузке списка (смена месяца/дня/reload); если они разошлись, ответ относится к
 * старому диапазону и отбрасывается (null) — иначе его карточки попали бы в новый список
 * и сдвинули offset. Иначе — слияние по id без дублей.
 */
export function mergeMorePage(
  items: SessionResponseV2[],
  page: SessionResponseV2[],
  startedEpoch: number,
  currentEpoch: number,
): SessionResponseV2[] | null {
  if (startedEpoch !== currentEpoch) {
    return null;
  }
  const known = new Set(items.map((item) => item.id));
  return [...items, ...page.filter((item) => !known.has(item.id))];
}
