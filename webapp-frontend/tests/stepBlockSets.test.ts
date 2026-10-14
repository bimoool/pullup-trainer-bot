import assert from "node:assert/strict";
import { test } from "node:test";

import { stepBlockSetsLine } from "../src/stepBlockSets.ts";

test("STEP-блок: рабочие + подход на максимум, итог совпадает с Live/Summary (3+1 = 4, 4+1 = 5)", () => {
  assert.equal(stepBlockSetsLine({ work_sets: 3, max_sets: 1 }), "3 рабочих подхода + подход на максимум · всего 4");
  assert.equal(stepBlockSetsLine({ work_sets: 4, max_sets: 1 }), "4 рабочих подхода + подход на максимум · всего 5");
});

test("склонение рабочих подходов и старый ответ без max_sets", () => {
  assert.equal(stepBlockSetsLine({ work_sets: 1, max_sets: 0 }), "1 рабочий подход");
  assert.equal(stepBlockSetsLine({ work_sets: 5 }), "5 рабочих подходов");
  assert.equal(stepBlockSetsLine({ work_sets: 2, max_sets: 2 }), "2 рабочих подхода + 2 подхода на максимум · всего 4");
});
