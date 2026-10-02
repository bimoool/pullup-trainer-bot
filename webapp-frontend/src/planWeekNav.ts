// issue #258 — навигация по неделям «Планов» и счётчики «сделано/план».
// Чистые функции без React/DOM: даты — строки YYYY-MM-DD (PlanWeek.start_date).

export interface WeekLike {
  id: number;
  start_date: string;
}

export interface ItemLike {
  count_per_week: number;
  done_count: number;
}

const MONTHS_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];

function parseDate(value: string): Date {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

function shortDate(date: Date): string {
  return `${date.getUTCDate()} ${MONTHS_SHORT[date.getUTCMonth()]}`;
}

/** «29 сен – 5 окт» для недели, начинающейся в startDate (понедельник). */
export function weekRangeLabel(startDate: string): string {
  const start = parseDate(startDate);
  const end = new Date(start.getTime() + 6 * 86_400_000);
  return `${shortDate(start)} – ${shortDate(end)}`;
}

/** Индекс текущей недели в списке по возрастанию start_date: последняя
 * неделя, начавшаяся не позже today; если все в будущем — первая. */
export function currentWeekIndex(weeks: WeekLike[], today: string): number {
  let index = 0;
  weeks.forEach((week, i) => {
    if (week.start_date <= today) {
      index = i;
    }
  });
  return index;
}

/** Индекс текущей недели: сервер отдаёт current_week_id (в часовом поясе
 * пользователя) — это источник истины; без него (старый ответ) — по локальной
 * дате устройства. «Последняя неделя» текущей НЕ считается: после #275 в
 * списке есть будущие недели. */
export function resolveCurrentWeekIndex(
  weeks: WeekLike[], currentWeekId: number | null | undefined, today: string,
): number {
  if (currentWeekId !== null && currentWeekId !== undefined) {
    const index = weeks.findIndex((week) => week.id === currentWeekId);
    if (index >= 0) {
      return index;
    }
  }
  return currentWeekIndex(weeks, today);
}

/** id текущей недели (см. resolveCurrentWeekIndex); null, если недель нет. */
export function resolveCurrentWeekId(
  weeks: WeekLike[], currentWeekId: number | null | undefined, today: string,
): number | null {
  if (weeks.length === 0) {
    return null;
  }
  return weeks[resolveCurrentWeekIndex(weeks, currentWeekId, today)].id;
}

/** Выбранная неделя ограничена списком: ‹ не уходит левее первой, › —
 * правее последней существующей (будущих недель нет → стоп на текущей). */
export function stepWeek(index: number, delta: -1 | 1, weekCount: number): number {
  return Math.min(Math.max(index + delta, 0), Math.max(weekCount - 1, 0));
}

/** issue #275 — на сколько недель вперёд можно планировать (как на бэкенде). */
export const MAX_FUTURE_WEEKS = 4;

/** › доступна, если следующая неделя уже есть, либо её можно создать
 * (последняя существующая ещё не дальше текущей на MAX_FUTURE_WEEKS). */
export function canAdvanceWeek(index: number, weekCount: number, currentIndex: number): boolean {
  if (index < weekCount - 1) {
    return true;
  }
  return index - currentIndex < MAX_FUTURE_WEEKS;
}

/** Редактировать (добавлять/переносить) можно текущую и будущие недели. */
export function isEditableWeek(index: number, currentIndex: number): boolean {
  return index >= currentIndex;
}

/** Локальная дата YYYY-MM-DD устройства. */
export function localToday(now: Date = new Date()): string {
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/** Группа = одна тренировка из нескольких PlanItem (Блок A/Б одной сессии):
 * выполнений — максимум по items (сессия привязана ко всем), план — максимум. */
export function groupCounter(items: ItemLike[]): { done: number; planned: number } {
  const planned = Math.max(0, ...items.map((item) => item.count_per_week));
  const done = Math.max(0, ...items.map((item) => item.done_count));
  return { done, planned };
}

/** Прогресс недели «N из M»: сумма min(сделано, план) по группам. */
export function weekProgress(groups: ItemLike[][]): { done: number; total: number } {
  let done = 0;
  let total = 0;
  for (const items of groups) {
    const counter = groupCounter(items);
    done += Math.min(counter.done, counter.planned);
    total += counter.planned;
  }
  return { done, total };
}
