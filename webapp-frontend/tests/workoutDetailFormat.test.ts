import assert from "node:assert/strict";
import { test } from "node:test";

import {
  estimateWorkoutSeconds, formatEstimate, formatItemSummary,
} from "../src/workoutDetailFormat.ts";

const item = (protocol: Record<string, unknown>) => ({
  id: 1, exercise_id: 1, exercise_name: "Х", order_index: 0, protocol,
});
const reps = { type: "reps_sets", prescription: { source: "static", sets: 3, reps: 8 }, rest_seconds: 60 };
const timeSets = { type: "time_sets", prescription: { source: "static", sets: 3, duration_seconds: 30 }, rest_seconds: 60 };
const interval = { type: "interval", total_duration_seconds: 180, work_seconds: 20, rest_seconds: 10, starts_with: "work" };

test("сводка упражнения: подходы × повторения · отдых", () => {
  assert.equal(formatItemSummary(reps), "3 × 8 повторений · отдых 1:00");
  assert.equal(formatItemSummary({ ...reps, rest_seconds: 0 }), "3 × 8 повторений");
});

test("оценка: time_sets и interval считаются, повторения — нет", () => {
  assert.equal(estimateWorkoutSeconds([item(timeSets)]), 3 * 30 + 2 * 60);
  assert.equal(estimateWorkoutSeconds([item(timeSets), item(interval)]), 210 + 180);
  assert.equal(estimateWorkoutSeconds([item(timeSets), item(reps)]), null);
  assert.equal(estimateWorkoutSeconds([]), null);
});

test("формат оценки округляет вверх и скрывает пустое", () => {
  assert.equal(formatEstimate(390), "≈ 7 мин");
  assert.equal(formatEstimate(null), null);
});
