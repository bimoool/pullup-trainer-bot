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

/** «9 окт» для даты YYYY-MM-DD. */
export function shortDateLabel(isoDate: string): string {
  return shortDate(parseDate(isoDate));
}

/** issue #304 — производное состояние занятия (сервер) → подпись на строке плана. null — без подписи. */
export interface OccurrenceLike {
  state?: string | null;
  available_from?: string | null;
}

export function occurrenceStateLabel(item: OccurrenceLike): string | null {
  switch (item.state) {
    case "too_early":
      return item.available_from ? `Доступно с ${shortDateLabel(item.available_from)}` : "Ещё рано";
    case "infeasible":
      return "Не успеть на этой неделе";
    case "missed":
      return "Пропущено";
    default:
      return null;
  }
}

/** Занятие курса для старта «по плану» без явного выбора: первое незасчитанное занятие курса в неделе
 * (по номеру), предпочтительно не «не успеть»; одна строка = одно занятие (#304). */
export function nextOccurrenceId(
  items: { id: number; program_inclusion_id: number | null; plan_week_id: number | null; occurrence_index?: number | null; state?: string | null }[],
  inclusionId: number, weekId: number | null,
): number | null {
  const candidates = items
    .filter((item) => item.program_inclusion_id === inclusionId && item.plan_week_id === weekId
      && item.occurrence_index !== null && item.occurrence_index !== undefined && item.state !== "completed")
    .sort((a, b) => (a.occurrence_index ?? 0) - (b.occurrence_index ?? 0));
  const preferred = candidates.find((item) => item.state !== "infeasible") ?? candidates[0];
  return preferred?.id ?? null;
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

/** Ширина полосы прогресса, 0–100 (целое): сделано/план, зажато в границы; пустой план — 0. */
export function progressPercent(done: number, total: number): number {
  if (!(total > 0) || !(done > 0)) {
    return 0;
  }
  return Math.min(100, Math.round((done / total) * 100));
}

/** Целых дней от a до b (даты YYYY-MM-DD, без часовых поясов и перевода часов). */
export function daysBetween(a: string, b: string): number {
  return Math.round((parseDate(b).getTime() - parseDate(a).getTime()) / 86_400_000);
}

/** Индекс «сегодня» внутри недели по соглашению PlanItem.day_of_week: 0 = понедельник … 6 = воскресенье.
 * today — дата пользователя с сервера (plan.today, #288), а не часы устройства; вне недели (today до её
 * начала или после конца: устаревший ответ, смена суток) — null, и «Сегодня» не рисуется. */
export function todayDayIndexInWeek(weekStartDate: string, today: string): number | null {
  const index = daysBetween(weekStartDate, today);
  return index >= 0 && index <= 6 ? index : null;
}
