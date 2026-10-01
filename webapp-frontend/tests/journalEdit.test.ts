import assert from "node:assert/strict";
import { test } from "node:test";

import type { SessionResponseV2 } from "../src/apiV2.ts";
import { buildEditPayload, initialDraft, isDateAllowed, trimDecimal } from "../src/journalEdit.ts";

const TZ = "Europe/Moscow";
const NOW = new Date("2026-10-01T12:00:00Z"); // 15:00 МСК, 1 октября

function session(): SessionResponseV2 {
  return {
    id: 1, source: "plan", status: "completed", performed_at: "2026-09-30T21:30:00Z", // 1 октября 00:30 МСК
    effort: "3.0", comment: "ок", title: "Моя", can_delete: true, can_edit: true,
    progression_result: null, progression_skipped_reason: null,
    blocks: [{
      order_index: 0, exercise_id: 5, complex_id: null, result: null, protocol_type: "reps_sets",
      exercise_name: "Подтягивания", started_at: null, set_targets: [], interval_config: null,
      set_logs: [
        { set_number: 1, is_max_set: false, metric_type: "reps", value: "8.00", unit: "reps", effort: null, note: null },
        { set_number: 2, is_max_set: false, metric_type: "reps", value: "7.50", unit: "reps", effort: "4.0", note: "тяжело" },
      ],
    }],
  } as unknown as SessionResponseV2;
}

test("trimDecimal убирает хвостовые нули", () => {
  assert.equal(trimDecimal("8.00"), "8");
  assert.equal(trimDecimal("7.50"), "7.5");
});

test("initialDraft: локальный день пользователя, значения подходов, усилие", () => {
  const draft = initialDraft(session(), TZ);
  assert.equal(draft.date, "2026-10-01");
  assert.equal(draft.effort, "3");
  assert.deepEqual(draft.sets.map((s) => [s.setNumber, s.value, s.effort, s.note]), [
    [1, "8", "", ""], [2, "7.5", "4", "тяжело"],
  ]);
});

test("isDateAllowed: сегодня можно, завтра и мусор — нет", () => {
  assert.equal(isDateAllowed("2026-10-01", TZ, NOW), true);
  assert.equal(isDateAllowed("2026-09-01", TZ, NOW), true);
  assert.equal(isDateAllowed("2026-10-02", TZ, NOW), false);
  assert.equal(isDateAllowed("", TZ, NOW), false);
});

test("buildEditPayload: дата не уходит, если не менялась; пустые усилие/комментарий -> null", () => {
  const draft = initialDraft(session(), TZ);
  draft.effort = "";
  draft.comment = "  ";
  draft.sets[0].value = "10";
  draft.sets[0].effort = "2";
  const result = buildEditPayload(session(), draft, TZ, NOW);
  assert.ok(result.ok);
  assert.equal(result.payload.performed_on, undefined);
  assert.equal(result.payload.effort, null);
  assert.equal(result.payload.comment, null);
  assert.deepEqual(result.payload.sets[0], { block_index: 0, set_number: 1, value: "10", effort: "2", note: null });
});

test("buildEditPayload: смена даты, будущая дата и плохие значения отклоняются", () => {
  const draft = initialDraft(session(), TZ);
  draft.date = "2026-09-20";
  const moved = buildEditPayload(session(), draft, TZ, NOW);
  assert.ok(moved.ok && moved.payload.performed_on === "2026-09-20");

  assert.equal(buildEditPayload(session(), { ...draft, date: "2026-10-05" }, TZ, NOW).ok, false);
  for (const bad of ["", "-1", "abc", "100000"]) {
    const broken = initialDraft(session(), TZ);
    broken.sets[1].value = bad;
    assert.equal(buildEditPayload(session(), broken, TZ, NOW).ok, false, `value=${bad}`);
  }
});
