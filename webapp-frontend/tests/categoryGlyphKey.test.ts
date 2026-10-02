import assert from "node:assert/strict";
import { test } from "node:test";

import { categoryGlyphKey } from "../src/categoryGlyphKey.ts";

test("глиф по ключевым словам названия категории", () => {
  assert.equal(categoryGlyphKey("Сила и мощность", 3), "dumbbell");
  assert.equal(categoryGlyphKey("Выносливость", 0), "pulse");
  assert.equal(categoryGlyphKey("Подтягивания", 0), "hang");
  assert.equal(categoryGlyphKey("Гибкость", 2), "wave");
  assert.equal(categoryGlyphKey("Общая физическая подготовка", 1), "figure");
});

test("без совпадения — глиф по порядку ряда, циклично и без отрицательных индексов", () => {
  assert.equal(categoryGlyphKey("e2e_xyz", 0), "dumbbell");
  assert.equal(categoryGlyphKey("e2e_xyz", 1), "pulse");
  assert.equal(categoryGlyphKey("e2e_xyz", 6), "dumbbell");
  assert.equal(categoryGlyphKey("", -1), "flame");
});
