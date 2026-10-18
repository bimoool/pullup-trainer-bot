// UX-01/02/08/09/20/32/33 (кампания ux-ref-20261018, исполнитель B) — чистая логика строк «Планов» и карточки
// курса. Без React/DOM. Факты приходят с сервера (CONTRACT_A_B v1); весь русский текст живёт здесь.
//
// Правило: «Начать» показываем тогда и только тогда, когда сервер сказал start_allowed. Пока бэкенд не отдаёт
// поле (старый ответ), выводим то же самое из `state` — те же причины, что у сервера, ничего нового.

import type { InclusionScheduleV2, PlanBlockedReason, PlanItemResponseV2 } from "./apiV2";
import { shortDateLabel } from "./planWeekNav.ts";

/** Единое написание блоков курса: кириллические «А» и «Б» (UX-09). */
export const VARIANT_LABELS = { A: "Объём (А)", B: "Сила (Б)" } as const;

/** Латинские «A»/«B» из серверных текстов («A и B по очереди», «Блок A») → «А»/«Б». Трогает только одиночные
 * буквы-слова/хвосты после слова «блок»/«Следующая тренировка», не слова вроде «BMI». */
export function normalizeBlockLetters(text: string): string {
  return text
    .replace(/(^|[^\p{L}\p{N}])A(?![\p{L}\p{N}])/gu, "$1А")
    .replace(/(^|[^\p{L}\p{N}])B(?![\p{L}\p{N}])/gu, "$1Б");
}

type RowFacts = Pick<
  PlanItemResponseV2,
  "state" | "start_allowed" | "blocked_reason" | "available_from" | "session_variant" | "session_ordinal"
>;

/** Можно ли показывать «Начать» (single source: start_allowed; без него — вывод из state). */
export function isStartAllowed(item: RowFacts): boolean {
  if (typeof item.start_allowed === "boolean") {
    return item.start_allowed;
  }
  return !(["too_early", "infeasible", "completed", "missed"] as const).some((state) => state === item.state);
}

/** Кнопка старта на строке плана. Занятия курса — строго по start_allowed. Свои/ручные строки (без курса)
 * сохраняют прежнее поведение: «рано» не стартуем, завершённую можно повторить («Ещё раз», #277), остальное —
 * по серверному start_allowed, если он есть. */
export function isRowStartable(item: RowFacts & Pick<PlanItemResponseV2, "program_inclusion_id">): boolean {
  if (item.program_inclusion_id !== null && item.program_inclusion_id !== undefined) {
    return isStartAllowed(item);
  }
  if (item.state === "completed") {
    return true;
  }
  return isStartAllowed(item);
}

/** Почему «Начать» нет (null — можно начать). */
export function blockedReason(item: RowFacts): PlanBlockedReason | null {
  if (isStartAllowed(item)) {
    return null;
  }
  if (item.blocked_reason) {
    return item.blocked_reason;
  }
  const state = item.state;
  return state === "too_early" || state === "infeasible" || state === "completed" || state === "missed" ? state : null;
}

/** Подпись состояния строки; у разрешённой к старту строки — null (подпись не нужна, есть кнопка). */
export function rowStatusLabel(item: RowFacts & Partial<Pick<PlanItemResponseV2, "program_inclusion_id">>): string | null {
  if (item.state === "completed" && (item.program_inclusion_id === null || item.program_inclusion_id === undefined)) {
    return null; // своя строка: счётчик «1/1» и «Ещё раз» уже говорят о выполнении
  }
  switch (blockedReason(item)) {
    case "too_early":
      return item.available_from ? `Доступно с ${shortDateLabel(item.available_from)}` : "Откроется после отдыха между тренировками";
    case "infeasible":
      return "Не уместится на этой неделе";
    case "completed":
      return "Выполнено";
    case "missed":
      return "Пропущено";
    case "no_access":
      return "Нужна подписка";
    default:
      return item.state === "awaiting_assessment" ? "Сначала тест на максимум" : null;
  }
}

/** Название занятия курса: «Объём (А)» / «Сила (Б)» + «занятие 2 из 3» (total — число основных занятий недели). */
export function variantLabel(item: RowFacts): string | null {
  return item.session_variant ? VARIANT_LABELS[item.session_variant] : null;
}

export function ordinalLabel(item: RowFacts, total: number | null): string | null {
  if (item.session_ordinal == null) {
    return null;
  }
  return total && total >= item.session_ordinal
    ? `занятие ${item.session_ordinal} из ${total}`
    : `занятие ${item.session_ordinal}`;
}

/** Подпись под названием строки: «Объём (А) · занятие 2 из 3» (части, которых нет, пропускаются). */
export function rowSubtitle(item: RowFacts, total: number | null): string | null {
  const parts = [variantLabel(item), ordinalLabel(item, total)].filter((part): part is string => part !== null);
  return parts.length > 0 ? parts.join(" · ") : null;
}

/** Для «Объём (А)» ожидается «проецированное» значение — честно помечаем, если оно не по факту прогрессии. */
export function isProjectedVariant(item: Pick<PlanItemResponseV2, "session_variant_basis">): boolean {
  return item.session_variant_basis === "projected";
}

function sessionsWord(count: number): string {
  const last = count % 10;
  const lastTwo = count % 100;
  if (last === 1 && lastTwo !== 11) {
    return "занятие";
  }
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) {
    return "занятия";
  }
  return "занятий";
}

export interface ScheduleExplanation {
  /** Заголовок: «Расписание вашей версии курса: 3 занятия в неделю». */
  headline: string;
  /** Честное следствие, если не всё уместится из-за отдыха (иначе null). */
  consequence: string | null;
  /** Старая версия курса (3 в неделю) — для тестов/стилей. */
  isLegacyThree: boolean;
}

/** UX-06/32: расписание словами. Для не-устаревшего 2/неделю тоже коротко говорим, сколько занятий. */
export function describeSchedule(schedule: InclusionScheduleV2 | null | undefined): ScheduleExplanation | null {
  if (!schedule || !(schedule.sessions_per_week > 0)) {
    return null;
  }
  const count = schedule.sessions_per_week;
  const isLegacyThree = schedule.is_legacy && count === 3;
  const headline = schedule.is_legacy
    ? `Расписание вашей версии курса: ${count} ${sessionsWord(count)} в неделю`
    : `Расписание курса: ${count} ${sessionsWord(count)} в неделю`;
  const consequence = schedule.weekly_capacity < count
    ? `Не все занятия уместятся: между тренировками нужен отдых (${schedule.min_days_between_starts} дня), поэтому за неделю получится не больше ${schedule.weekly_capacity}.`
    : null;
  return { headline, consequence, isLegacyThree };
}

/** Число основных занятий курса в неделе — знаменатель «занятие N из M». */
export function weekOccurrenceTotal(
  items: Pick<PlanItemResponseV2, "program_inclusion_id" | "plan_week_id" | "occurrence_index">[],
  inclusionId: number | null, weekId: number | null,
): number {
  return items.filter((item) => item.program_inclusion_id === inclusionId && item.plan_week_id === weekId
    && item.occurrence_index !== null && item.occurrence_index !== undefined).length;
}

/** UX-33: строка счётчика на карточке курса. */
export function electiveCounterLabel(entriesThisWeek: number, limit: number): string {
  return `Факультативы: ${entriesThisWeek} из ${limit} на этой неделе`;
}

export const ELECTIVE_EXPLANATION = "Бесплатно, до 2 в неделю, на прогрессию курса не влияют.";
export const ELECTIVE_REST_DAY_HINT = "Сегодня отдых — можно факультатив";
export const ELECTIVE_LIMIT_TEXT = "Лимит факультативов на этой неделе исчерпан — новый откроется через несколько дней.";
