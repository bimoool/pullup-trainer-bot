/** Чистые помощники записи в Журнал (CRIMPD #263): свободная активность и
 * тренировка задним числом. Без React/сети — покрыты tests/journalLog.test.ts. */

import { noonInTimeZoneIso, todayInTimeZone } from "./todayInTimeZone.ts";

export const ACTIVITY_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: "running", label: "Бег" },
  { value: "cycling", label: "Велосипед" },
  { value: "swimming", label: "Плавание" },
  { value: "hiking", label: "Ходьба/хайкинг" },
  { value: "yoga", label: "Йога/растяжка" },
  { value: "gym", label: "Силовая в зале" },
  { value: "martial_arts", label: "Единоборства" },
  { value: "other", label: "Другое" },
];

export const MIN_ACTIVITY_SECONDS = 60;
export const MAX_ACTIVITY_SECONDS = 12 * 3600;

/** "1:30" / "0:45" / "12:00" (ч:мм) -> секунды; null — не распознано. */
export function parseDurationHm(text: string): number | null {
  const match = /^(\d{1,2}):([0-5]\d)$/.exec(text.trim());
  if (match === null) {
    return null;
  }
  return Number(match[1]) * 3600 + Number(match[2]) * 60;
}

/** Секунды -> "ч:мм" (5400 -> "1:30"). */
export function formatDurationHm(seconds: number): string {
  const totalMinutes = Math.floor(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  return `${hours}:${String(totalMinutes % 60).padStart(2, "0")}`;
}

/** Текст ошибки поля «Длительность» или null, если значение допустимо (1 мин – 12 ч). */
export function durationError(text: string): string | null {
  const seconds = parseDurationHm(text);
  if (seconds === null) {
    return "Введи длительность в формате ч:мм, например 1:30";
  }
  if (seconds < MIN_ACTIVITY_SECONDS || seconds > MAX_ACTIVITY_SECONDS) {
    return "Длительность — от 0:01 до 12:00";
  }
  return null;
}

/** Дата не из будущего (YYYY-MM-DD сравнивается лексикографически). */
export function dateError(date: string, today: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return "Выбери дату";
  }
  return date > today ? "Дата не может быть в будущем" : null;
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** Локальная дата YYYY-MM-DD устройства. */
export function localToday(now: Date = new Date()): string {
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** performed_at для выбранного дня: сегодня (в поясе профиля, #294) — «сейчас» (не уйдёт в будущее), прошлый
 * день — полдень в поясе профиля (стабильно попадает в этот же день в любом поясе ±12 ч). */
export function performedAtFor(date: string, now: Date = new Date(), timeZone?: string): string {
  if (date === todayInTimeZone(timeZone, now)) {
    return now.toISOString();
  }
  return noonInTimeZoneIso(date, timeZone);
}

/** Сколько полей подхода показать для упражнения по протоколу тренировки. */
export function setCountForProtocol(protocol: Record<string, unknown>): number {
  const prescription = protocol.prescription;
  if (prescription !== null && typeof prescription === "object") {
    const record = prescription as Record<string, unknown>;
    for (const key of ["sets", "attempts"]) {
      const value = record[key];
      if (typeof value === "number" && Number.isInteger(value) && value >= 1) {
        return Math.min(value, 20);
      }
    }
  }
  return 1;
}

/** Единица значения подхода: время — секунды, всё остальное — повторения. */
export function metricForProtocol(protocol: Record<string, unknown>): { metric_type: "reps" | "time"; unit: "reps" | "s" } {
  return protocol.type === "time_sets" || protocol.type === "interval"
    ? { metric_type: "time", unit: "s" }
    : { metric_type: "reps", unit: "reps" };
}

export interface BackdatedExerciseInput {
  exerciseId: number;
  protocol: Record<string, unknown>;
  /** Введённые значения подходов (повторения или секунды); пустые пропускаются. */
  values: string[];
}

export interface SessionCreatePayload {
  source: "backdated" | "freeform";
  performed_at: string;
  effort: string | null;
  comment: string | null;
  blocks: {
    exercise_id: number;
    sets: { set_number: number; metric_type: string; value: string; unit: string }[];
  }[];
  activity_type?: string;
  duration_seconds?: number;
}

function cleanComment(comment: string): string | null {
  const trimmed = comment.trim().slice(0, 1000);
  return trimmed === "" ? null : trimmed;
}

/** Тело запроса записи сессии для «Тренировку из моих». Упражнения без введённых
 * подходов не попадают в запись; null — нечего записывать. */
export function buildBackdatedPayload(
  date: string, exercises: BackdatedExerciseInput[], effort: string | null, comment: string, now: Date = new Date(), timeZone?: string,
): SessionCreatePayload | null {
  const blocks = exercises.flatMap((exercise) => {
    const metric = metricForProtocol(exercise.protocol);
    const sets = exercise.values
      .map((value) => value.trim().replace(",", "."))
      .filter((value) => value !== "" && Number(value) > 0)
      .map((value, index) => ({ set_number: index + 1, ...metric, value }));
    return sets.length === 0 ? [] : [{ exercise_id: exercise.exerciseId, sets }];
  });
  if (blocks.length === 0) {
    return null;
  }
  return { source: "backdated", performed_at: performedAtFor(date, now, timeZone), effort, comment: cleanComment(comment), blocks };
}

/** Тело запроса записи сессии для «Другую активность». */
export function buildActivityPayload(
  date: string, activityType: string, durationText: string, effort: string | null, comment: string,
  now: Date = new Date(), timeZone?: string,
): SessionCreatePayload | null {
  const seconds = parseDurationHm(durationText);
  if (seconds === null) {
    return null;
  }
  return {
    source: "freeform", performed_at: performedAtFor(date, now, timeZone), effort, comment: cleanComment(comment),
    blocks: [], activity_type: activityType, duration_seconds: seconds,
  };
}
