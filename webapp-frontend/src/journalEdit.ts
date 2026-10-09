import type { SessionEditRequestV2, SessionResponseV2 } from "./apiV2";
import { WORKOUT_COMMENT_MAX } from "./effortScale.ts";
import { localDateKey } from "./journalCalendarModel.ts";
import { durationError, formatDurationHm, parseDurationHm } from "./journalLog.ts";

/** Лимиты зеркалят app/web/schemas_v2_session.py::SessionSetEditSchema. */
export const SET_NOTE_MAX = 500;
export const SET_VALUE_MAX = 99999.99;

export interface SetDraft {
  blockIndex: number;
  setNumber: number;
  unit: string;
  value: string;
  effort: string; // "" — без усилия
  note: string;
}

export interface EditDraft {
  date: string; // YYYY-MM-DD, локальный день пользователя
  effort: string; // "" — без оценки
  comment: string;
  sets: SetDraft[];
  /** #307 (J9): внешняя активность — тип и длительность ч:мм; null у силовой записи. */
  activity: { type: string; duration: string } | null;
}

/** Число без хвостовых нулей: "8.00" → "8", "7.50" → "7.5". */
export function trimDecimal(value: string): string {
  const number = Number(value);
  return Number.isFinite(number) ? String(number) : value;
}

export function initialDraft(session: SessionResponseV2, timeZone: string): EditDraft {
  return {
    date: localDateKey(session.performed_at, timeZone),
    effort: session.effort === null ? "" : String(Math.round(Number(session.effort))),
    comment: session.comment ?? "",
    sets: session.blocks.flatMap((block) =>
      block.set_logs.map((log) => ({
        blockIndex: block.order_index,
        setNumber: log.set_number,
        unit: log.unit,
        value: trimDecimal(log.value),
        effort: log.effort === null ? "" : String(Math.round(Number(log.effort))),
        note: log.note ?? "",
      })),
    ),
    activity: session.activity_type
      ? {
        type: session.activity_type,
        duration: session.duration_seconds != null ? formatDurationHm(session.duration_seconds) : "",
      }
      : null,
  };
}

export function todayKey(timeZone: string, now: Date = new Date()): string {
  return localDateKey(now.toISOString(), timeZone);
}

/** Дата не в будущем (сравнение строк YYYY-MM-DD корректно). */
export function isDateAllowed(date: string, timeZone: string, now: Date = new Date()): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(date) && date <= todayKey(timeZone, now);
}

export type PayloadResult = { ok: true; payload: SessionEditRequestV2 } | { ok: false; error: string };

/** Черновик → тело PATCH. Дата уходит только если изменилась; подходы — все
 * (значения/усилие/заметка заменяются целиком). */
export function buildEditPayload(
  session: SessionResponseV2, draft: EditDraft, timeZone: string, now: Date = new Date(),
): PayloadResult {
  if (!isDateAllowed(draft.date, timeZone, now)) {
    return { ok: false, error: "Дата не может быть в будущем." };
  }
  if (draft.comment.trim().length > WORKOUT_COMMENT_MAX) {
    return { ok: false, error: `Комментарий — не длиннее ${WORKOUT_COMMENT_MAX} символов.` };
  }
  const sets = [];
  for (const set of draft.sets) {
    const value = Number(set.value);
    if (set.value.trim() === "" || !Number.isFinite(value) || value < 0 || value > SET_VALUE_MAX) {
      return { ok: false, error: `Подход ${set.setNumber}: укажите значение от 0 до ${SET_VALUE_MAX}.` };
    }
    if (set.note.trim().length > SET_NOTE_MAX) {
      return { ok: false, error: `Подход ${set.setNumber}: заметка длиннее ${SET_NOTE_MAX} символов.` };
    }
    sets.push({
      block_index: set.blockIndex,
      set_number: set.setNumber,
      value: set.value.trim(),
      effort: set.effort === "" ? null : set.effort,
      note: set.note.trim() === "" ? null : set.note.trim(),
    });
  }
  const payload: SessionEditRequestV2 = {
    effort: draft.effort === "" ? null : draft.effort,
    comment: draft.comment.trim() === "" ? null : draft.comment.trim(),
    sets,
  };
  if (draft.date !== localDateKey(session.performed_at, timeZone)) {
    payload.performed_on = draft.date;
  }
  if (draft.activity !== null) {
    const problem = durationError(draft.activity.duration);
    if (problem !== null) {
      return { ok: false, error: problem };
    }
    const seconds = parseDurationHm(draft.activity.duration);
    if (seconds !== null && seconds !== session.duration_seconds) {
      payload.duration_seconds = seconds;
    }
    if (draft.activity.type !== session.activity_type) {
      payload.activity_type = draft.activity.type;
    }
  }
  return { ok: true, payload };
}
