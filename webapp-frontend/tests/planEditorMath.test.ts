import assert from "node:assert/strict";
import { test } from "node:test";

import type { EditorWeekV2 } from "../src/apiV2.ts";
import { dayTotals, nextPhase, quantityBounds, remainingLabel, weekEmptyNote, weekTotals } from "../src/planEditorMath.ts";

const week = (q: Record<string, number>, done: Record<string, number>, state: EditorWeekV2["state"]): EditorWeekV2 => ({
  index: 1, week_number: 1, start_date: "2026-10-05", state, phase: "base",
  total: Object.values(q).reduce((a, b) => a + b, 0), quantities: q, done, placed: 0,
});

test("weekTotals: A 2/2/0/1 + B 1/1/1/1 => 3/3/1/2", () => {
  const weeks = [{ a: 2, b: 1 }, { a: 2, b: 1 }, { a: 0, b: 1 }, { a: 1, b: 1 }].map((q) => ({ quantities: q }));
  assert.deepEqual(weekTotals(weeks), [3, 3, 1, 2]);
});

test("quantityBounds: floor is done count, past weeks frozen, max 14 per week", () => {
  const w = week({ "1": 2 }, { "1": 1 }, "current");
  assert.deepEqual(quantityBounds(w, 1), { min: 1, canInc: true, canDec: true });
  assert.equal(quantityBounds(week({ "1": 1 }, { "1": 1 }, "current"), 1).canDec, false);
  assert.equal(quantityBounds(week({ "1": 1 }, {}, "past"), 1).canInc, false);
  assert.equal(quantityBounds(week({ "1": 14 }, {}, "future"), 1).canInc, false);
});

test("remainingLabel and dayTotals: A x2 on Tuesday + B on Thursday", () => {
  assert.equal(remainingLabel(1), "осталось разместить 1");
  assert.equal(remainingLabel(0), "все занятия размещены");
  assert.deepEqual(dayTotals([{ placed_by_day: [0, 2, 0, 0, 0, 0, 0] }, { placed_by_day: [0, 0, 0, 1, 0, 0, 0] }]), [0, 2, 0, 1, 0, 0, 0]);
});

test("phase cycle and empty-week note", () => {
  assert.equal(nextPhase("base"), "rest");
  assert.equal(nextPhase("peak"), "base");
  assert.equal(weekEmptyNote(0), "Неделя отдыха по плану");
  assert.equal(weekEmptyNote(2), null);
});
