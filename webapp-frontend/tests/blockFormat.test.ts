import assert from "node:assert/strict";
import { test } from "node:test";

import { resultInputLabel } from "../src/blockFormat.ts";

const t = (value: string, unit: string) => ({ set_number: 1, metric_type: "x", value, unit });

test("reps target -> «Повторений» with target hint", () => {
  assert.deepEqual(resultInputLabel("reps_sets", t("8.00", "reps")), { label: "Повторений", hint: "Цель: 8 повт." });
});

test("time target -> «Секунды» with target hint", () => {
  assert.deepEqual(resultInputLabel("time_sets", t("30", "s")), { label: "Секунды", hint: "Цель: 0:30" });
});

test("max block -> «Повторений», no invented hint", () => {
  assert.deepEqual(resultInputLabel("max_effort", t("0", "reps")), { label: "Повторений", hint: null });
});

test("unknown unit -> fallback «Результат»", () => {
  assert.deepEqual(resultInputLabel("reps_sets", t("5", "kg")), { label: "Результат", hint: "Цель: 5 kg" });
  assert.deepEqual(resultInputLabel(null, null), { label: "Результат", hint: null });
});

test("course max set (issue #305) -> «Повторений», no «Цель: 0» hint", () => {
  const maxSet = { ...t("0", "reps"), is_max_set: true };
  assert.deepEqual(resultInputLabel(null, maxSet), { label: "Повторений", hint: null });
  assert.deepEqual(resultInputLabel(null, t("3", "reps")), { label: "Повторений", hint: "Цель: 3 повт." });
});
