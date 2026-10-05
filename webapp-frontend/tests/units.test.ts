import assert from "node:assert/strict";
import { test } from "node:test";

import { PALETTES, resolveAppearance } from "../src/theme.ts";
import {
  convertHeightText,
  convertWeightText,
  formatHeight,
  formatWeight,
  unitToCm,
  unitToKg,
} from "../src/units.ts";

test("formatWeight/formatHeight: метрика как есть, имперские — пересчёт", () => {
  assert.equal(formatWeight("80.50", "kg"), "80.5 кг");
  assert.equal(formatWeight("80", "lb"), "176.4 фунт.");
  assert.equal(formatWeight(null, "lb"), "не указано");
  assert.equal(formatHeight(180, "cm"), "180 см");
  assert.equal(formatHeight(180, "in"), "70.9 дюйм.");
  assert.equal(formatHeight(null, "in"), "не указано");
});

test("unitToKg/unitToCm: ввод в имперских единицах уходит в метрику", () => {
  assert.equal(unitToKg(176.4, "lb"), 80.01);
  assert.equal(unitToKg(80, "kg"), 80);
  assert.equal(unitToCm(71, "in"), 180);
  assert.equal(unitToCm(180.4, "cm"), 180);
});

test("convertWeightText/convertHeightText: смена единицы переводит текст поля, пустое не трогает", () => {
  assert.equal(convertWeightText("80", "kg", "lb"), "176.4");
  assert.equal(convertWeightText("", "kg", "lb"), "");
  assert.equal(convertWeightText("abc", "kg", "lb"), "abc");
  assert.equal(convertWeightText("80", "kg", "kg"), "80");
  assert.equal(convertWeightText("75.00", "kg", "kg"), "75");
  assert.equal(convertHeightText("180", "cm", "in"), "70.9");
  assert.equal(convertHeightText("", "cm", "in"), "");
});

test("resolveAppearance: override побеждает схему Telegram, auto — следует ей", () => {
  assert.equal(resolveAppearance("dark", "light"), "dark");
  assert.equal(resolveAppearance("light", "dark"), "light");
  assert.equal(resolveAppearance("auto", "dark"), "dark");
  assert.equal(resolveAppearance("auto", undefined), undefined);
  assert.notEqual(PALETTES.light["bg-color"], PALETTES.dark["bg-color"]);
});
