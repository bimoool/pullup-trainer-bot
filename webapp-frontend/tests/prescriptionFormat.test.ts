import assert from "node:assert/strict";
import { test } from "node:test";

import { firstPrescriptionDescription, itemPrescriptionLine } from "../src/prescriptionFormat.ts";

const block = (key: string, description: string, rest: string | null) => ({
  key, exercise: { id: 1, display_name: "Подтягивания" }, kind: "sets" as const, description,
  rest_description: rest, prep_seconds: 5, rest_after_block_seconds: null, total_target_reps: null,
  sets: [], interval: null,
});

test("W-лесенка: строка рецепта — серверный describe(), не пересчёт 17 × 3", () => {
  const workout = { prescription: [block("i42", "5-4-3-2-1-2-3-4-5-4-3-2-1-2-3-4-5", "отдых 0:10")] };
  assert.equal(itemPrescriptionLine(workout, 42), "5-4-3-2-1-2-3-4-5-4-3-2-1-2-3-4-5 · отдых 0:10");
  assert.equal(firstPrescriptionDescription(workout), "5-4-3-2-1-2-3-4-5-4-3-2-1-2-3-4-5");
});

test("поподходный отдых и максимум без цели", () => {
  const workout = { prescription: [block("i7", "Максимум × 4", "отдых 3:00 → 2:00 → 1:00")] };
  assert.equal(itemPrescriptionLine(workout, 7), "Максимум × 4 · отдых 3:00 → 2:00 → 1:00");
});

test("нет версии или блока — null (экран показывает V1-сводку)", () => {
  assert.equal(itemPrescriptionLine({ prescription: null }, 1), null);
  assert.equal(itemPrescriptionLine({}, 1), null);
  assert.equal(itemPrescriptionLine({ prescription: [block("i2", "3 × 10", null)] }, 1), null);
  assert.equal(itemPrescriptionLine({ prescription: [block("i1", "3 × 10", null)] }, 1), "3 × 10");
  assert.equal(firstPrescriptionDescription({ prescription: [] }), null);
});
