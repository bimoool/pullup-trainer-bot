// issue #266 — обзор плана: «Сейчас | Завершённые» и превью расписания программы.
// Чистые функции без React/DOM.

export interface InclusionLike {
  is_active: boolean;
  started_at: string;
  expires_at: string | null;
  duration_weeks?: number | null;
  current_week?: number | null;
}

export interface ScheduleItemLike {
  week_phase: string;
  day_of_week: number | null;
}

const MONTHS_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];

export const DAY_NAMES_RU = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"];

export const PHASE_LABELS_RU: Record<string, string> = { base: "База", rest: "Отдых", peak: "Пик" };

/** «5 окт 2026» из ISO-времени (по локальной дате устройства). */
export function formatDay(iso: string): string {
  const date = new Date(iso);
  return `${date.getDate()} ${MONTHS_SHORT[date.getMonth()]} ${date.getFullYear()}`;
}

/** «1 сен 2026 – 5 окт 2026»; без даты окончания — «с 1 сен 2026». */
export function inclusionDateRange(inclusion: Pick<InclusionLike, "started_at" | "expires_at">): string {
  if (inclusion.expires_at === null) {
    return `с ${formatDay(inclusion.started_at)}`;
  }
  return `${formatDay(inclusion.started_at)} – ${formatDay(inclusion.expires_at)}`;
}

/** «Неделя 3 из 8» — только для курса с заданной длиной; иначе null (не выдумываем). */
export function inclusionWeekLabel(inclusion: Pick<InclusionLike, "duration_weeks" | "current_week">): string | null {
  if (!inclusion.duration_weeks || !inclusion.current_week) {
    return null;
  }
  return `Неделя ${inclusion.current_week} из ${inclusion.duration_weeks}`;
}

/** Завершённые = неактивные инклюзии, недавно завершённые сверху (id — тай-брейк). */
export function completedInclusions<T extends InclusionLike & { id: number }>(inclusions: T[]): T[] {
  const endedAt = (i: InclusionLike) => Date.parse(i.expires_at ?? i.started_at) || 0;
  return inclusions.filter((i) => !i.is_active).sort((a, b) => endedAt(b) - endedAt(a) || b.id - a.id);
}

/** Группировка строк превью по фазе (порядок появления) и дню: [фаза, строки]. */
export function groupScheduleByPhase<T extends ScheduleItemLike>(items: T[]): [string, T[]][] {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const list = groups.get(item.week_phase) ?? [];
    list.push(item);
    groups.set(item.week_phase, list);
  }
  return [...groups.entries()];
}
