import assert from "node:assert/strict";
import { test } from "node:test";

import { countNoun, plural } from "../src/plural.ts";
import { plural as blockPlural } from "../src/blockFormat.ts";
import { plural as protocolPlural } from "../src/protocolConfig.ts";

const W = ["тренировка", "тренировки", "тренировок"] as const;

test("plural: 1 / 2–4 / 5+ и особые 11–14, 21, 101, 111", () => {
  const cases: [number, string][] = [
    [0, "тренировок"], [1, "тренировка"], [2, "тренировки"], [4, "тренировки"], [5, "тренировок"],
    [10, "тренировок"], [11, "тренировок"], [12, "тренировок"], [14, "тренировок"], [15, "тренировок"],
    [21, "тренировка"], [22, "тренировки"], [25, "тренировок"], [101, "тренировка"], [111, "тренировок"], [112, "тренировок"],
  ];
  for (const [n, word] of cases) {
    assert.equal(plural(n, ...W), word, String(n));
  }
});

test("countNoun и общий хелпер у всех модулей", () => {
  assert.equal(countNoun(1, ...W), "1 тренировка");
  assert.equal(countNoun(3, ...W), "3 тренировки");
  assert.equal(countNoun(12, ...W), "12 тренировок");
  for (const n of [1, 2, 5, 11, 21]) {
    assert.equal(blockPlural(n, ...W), plural(n, ...W));
    assert.equal(protocolPlural(n, ...W), plural(n, ...W));
  }
});
