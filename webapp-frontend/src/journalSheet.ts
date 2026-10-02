// Чистый помощник шторки записи Журнала v2 (#280): какие действия доступны. Без зависимостей.

export type JournalSheetAction = "open" | "edit" | "clone" | "workout" | "delete";

type SheetSession = {
  source: string;
  can_edit: boolean;
  can_delete: boolean;
  workout_id?: number | null;
};

/** Порядок и метки действий шторки (Crimpd: View / Edit / Clone / Delete). */
export const JOURNAL_SHEET_LABELS: Record<JournalSheetAction, string> = {
  open: "Открыть",
  edit: "Изменить",
  clone: "Повторить",
  workout: "Открыть тренировку",
  delete: "Удалить",
};

/**
 * Доступные действия — ровно те же правила, что на экране деталей: «Изменить»/«Повторить» — по
 * can_edit (клон факультатива бэкенд отклоняет 409 — не предлагаем), «Открыть тренировку» — только
 * при workout_id и если экран умеет её открыть, «Удалить» — по can_delete. «Открыть» — всегда.
 */
export function journalSheetActions(
  session: SheetSession, opts: { canOpenWorkout: boolean },
): JournalSheetAction[] {
  const actions: JournalSheetAction[] = ["open"];
  if (session.can_edit) {
    actions.push("edit");
    if (session.source !== "elective") {
      actions.push("clone");
    }
  }
  if (opts.canOpenWorkout && session.workout_id != null) {
    actions.push("workout");
  }
  if (session.can_delete) {
    actions.push("delete");
  }
  return actions;
}

/** Подтверждение удаления записи v2 — одно и то же на экране деталей и в шторке. */
export const JOURNAL_DELETE_CONFIRM = "Удалить эту тренировку? Отменить это будет нельзя.";
