import assert from "node:assert/strict";
import { test } from "node:test";

import { collectionItemKindLabel, formatCollectionCount } from "../src/collectionsFormat.ts";

const counts = (programs: number, exercises: number) => ({
  items_count: programs + exercises, programs_count: programs, exercises_count: exercises,
});

test("formatCollectionCount: только программы — склонение по числу", () => {
  assert.equal(formatCollectionCount(counts(1, 0)), "1 программа");
  assert.equal(formatCollectionCount(counts(3, 0)), "3 программы");
  assert.equal(formatCollectionCount(counts(5, 0)), "5 программ");
  assert.equal(formatCollectionCount(counts(11, 0)), "11 программ");
  assert.equal(formatCollectionCount(counts(21, 0)), "21 программа");
});

test("formatCollectionCount: только упражнения", () => {
  assert.equal(formatCollectionCount(counts(0, 2)), "2 упражнения");
  assert.equal(formatCollectionCount(counts(0, 7)), "7 упражнений");
});

test("formatCollectionCount: смешанный состав — «элементов»", () => {
  assert.equal(formatCollectionCount(counts(2, 1)), "3 элемента");
  assert.equal(formatCollectionCount(counts(4, 1)), "5 элементов");
});

test("collectionItemKindLabel", () => {
  assert.equal(collectionItemKindLabel("program"), "Программа");
  assert.equal(collectionItemKindLabel("exercise"), "Упражнение");
});
