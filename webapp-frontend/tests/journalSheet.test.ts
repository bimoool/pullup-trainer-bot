import assert from "node:assert/strict";
import { test } from "node:test";

import { journalSheetActions } from "../src/journalSheet.ts";

const base = { source: "builder", can_edit: true, can_delete: true, workout_id: null as number | null };

test("запись, которую можно менять и удалять: открыть, изменить, повторить, удалить", () => {
  assert.deepEqual(journalSheetActions(base, { canOpenWorkout: true }), ["open", "edit", "clone", "delete"]);
});

test("workout_id добавляет «Открыть тренировку» между «Повторить» и «Удалить»", () => {
  assert.deepEqual(
    journalSheetActions({ ...base, workout_id: 7 }, { canOpenWorkout: true }),
    ["open", "edit", "clone", "workout", "delete"],
  );
});

test("без обработчика открытия тренировки действие не показывается", () => {
  assert.deepEqual(
    journalSheetActions({ ...base, workout_id: 7 }, { canOpenWorkout: false }),
    ["open", "edit", "clone", "delete"],
  );
});

test("факультатив: клона нет (бэкенд отвечает 409), остальное есть", () => {
  assert.deepEqual(
    journalSheetActions({ ...base, source: "elective" }, { canOpenWorkout: true }),
    ["open", "edit", "delete"],
  );
});

test("can_edit=false скрывает «Изменить» и «Повторить», can_delete=false — «Удалить»", () => {
  assert.deepEqual(
    journalSheetActions({ ...base, can_edit: false }, { canOpenWorkout: true }),
    ["open", "delete"],
  );
  assert.deepEqual(
    journalSheetActions({ ...base, can_delete: false, workout_id: 3 }, { canOpenWorkout: true }),
    ["open", "edit", "clone", "workout"],
  );
});

test("только чтение: остаётся «Открыть», тупика нет", () => {
  assert.deepEqual(
    journalSheetActions({ ...base, can_edit: false, can_delete: false }, { canOpenWorkout: true }),
    ["open"],
  );
});
