import assert from "node:assert/strict";
import { test } from "node:test";

import type { SessionResponseV2 } from "../src/apiV2.ts";
import { mergeMorePage } from "../src/journalPaging.ts";

const s = (id: number) => ({ id }) as SessionResponseV2;

test("mergeMorePage: слияние по id без дублей", () => {
  const merged = mergeMorePage([s(1), s(2)], [s(2), s(3)], 4, 4);
  assert.deepEqual(merged?.map((item) => item.id), [1, 2, 3]);
});

test("mergeMorePage: ответ старой эпохи (смена месяца/дня) отбрасывается", () => {
  assert.equal(mergeMorePage([s(10)], [s(1), s(2)], 4, 5), null);
});
