import assert from "node:assert/strict";
import { test } from "node:test";

import { EFFORT_SCALE, effortWithWord, reviewPayload } from "../src/effortScale.ts";

test("шкала: значения 1..5 неизменны, слова по порядку", () => {
  assert.deepEqual(EFFORT_SCALE.map((o) => o.value), ["1", "2", "3", "4", "5"]);
  assert.deepEqual(
    EFFORT_SCALE.map((o) => o.label),
    ["Очень легко", "Легко", "Средне", "Тяжело", "Предел"],
  );
});

test("effortWithWord: строка, число, Decimal-строка и пусто", () => {
  assert.equal(effortWithWord("4"), "4 Тяжело");
  assert.equal(effortWithWord(5), "5 Предел");
  assert.equal(effortWithWord("3.0"), "3 Средне");
  assert.equal(effortWithWord(null), null);
  assert.equal(effortWithWord("7"), "7");
});

test("reviewPayload: пустая заметка → null, обрезка по 1000", () => {
  assert.deepEqual(reviewPayload(null, "   "), { effort: null, comment: null });
  assert.deepEqual(reviewPayload("2", " ок "), { effort: "2", comment: "ок" });
  assert.equal(reviewPayload("2", "x".repeat(1500)).comment?.length, 1000);
});
