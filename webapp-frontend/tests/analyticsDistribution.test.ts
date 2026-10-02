import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CATEGORY_COLORS, NEUTRAL_COLOR, categoryColors, donutRings, formatPercent, formatShare, ringArcPath,
} from "../src/analyticsDistribution.ts";
import type { AnalyticsDistributionV2 } from "../src/apiV2.ts";

const dist: AnalyticsDistributionV2 = {
  categories: [
    {
      name: "Тяга", workouts: 1.5, minutes: 50,
      subcategories: [{ name: "Верт", workouts: 1, minutes: 40 }, { name: "Гориз", workouts: 0.25, minutes: 5 }],
    },
    { name: "Ноги", workouts: 0, minutes: 0, subcategories: [] },
    { name: "Кор", workouts: 0.5, minutes: 10, subcategories: [] },
    { name: "Другая активность", workouts: 1, minutes: 30, subcategories: [] },
  ],
  total_workouts: 3, total_minutes: 90,
};

test("categoryColors: палитра по порядку, служебная категория нейтральная", () => {
  const colors = categoryColors(dist);
  assert.equal(colors.get("Тяга"), CATEGORY_COLORS[0]);
  assert.equal(colors.get("Ноги"), CATEGORY_COLORS[1]);
  assert.equal(colors.get("Другая активность"), NEUTRAL_COLOR);
});

test("donutRings: внутреннее кольцо — категории без нулей, доли в сумме 1", () => {
  const { inner, outer, total } = donutRings(dist, "workouts");
  assert.equal(total, 3);
  assert.deepEqual(inner.map((s) => s.label), ["Тяга", "Кор", "Другая активность"]);
  assert.equal(inner[0].start, 0);
  assert.ok(Math.abs(inner[inner.length - 1].end - 1) < 1e-9);
  // внешнее: две подкатегории Тяги + остаток (0.25), затем Кор и «Другая» целиком
  assert.deepEqual(outer.map((s) => s.label), ["Верт", "Гориз", "Тяга", "Кор", "Другая активность"]);
  assert.ok(Math.abs(outer[outer.length - 1].end - 1) < 1e-9);
});

test("donutRings: метрика minutes и пустые данные", () => {
  assert.equal(donutRings(dist, "minutes").total, 90);
  const empty = donutRings({ categories: [{ name: "A", workouts: 0, minutes: 0, subcategories: [] }], total_workouts: 0, total_minutes: 0 }, "workouts");
  assert.deepEqual(empty, { inner: [], outer: [], total: 0 });
});

test("ringArcPath: полный круг не вырождается, large-arc для > половины", () => {
  const full = ringArcPath(90, 90, 40, 60, 0, 1);
  assert.match(full, /A60 60 0 1 1/);
  const small = ringArcPath(90, 90, 40, 60, 0, 0.25);
  assert.match(small, /A60 60 0 0 1/);
});

test("форматирование долей и процентов", () => {
  assert.equal(formatShare(1.5), "1.5");
  assert.equal(formatShare(2), "2");
  assert.equal(formatShare(0.6667), "0.67");
  assert.equal(formatPercent(1, 4), "25%");
  assert.equal(formatPercent(1, 0), "0%");
});
