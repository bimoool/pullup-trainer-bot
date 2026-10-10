import assert from "node:assert/strict";
import { test } from "node:test";

import {
  NEUTRAL_COLOR, categoryColors, donutRings, formatCount, formatPercent, ringArcPath,
} from "../src/analyticsDistributionModel.ts";
import { categoryColorVar } from "../src/homeDiscovery.ts";
import type { AnalyticsDistributionV2 } from "../src/apiV2.ts";

const dist: AnalyticsDistributionV2 = {
  categories: [
    {
      name: "Тяга", workouts: 3, minutes: 50,
      subcategories: [{ name: "Верт", workouts: 2, minutes: 40 }, { name: "Гориз", workouts: 1, minutes: 5 }],
    },
    { name: "Ноги", workouts: 0, minutes: 0, subcategories: [] },
    { name: "Кор", workouts: 1, minutes: 10, subcategories: [] },
    { name: "Другая активность", workouts: 2, minutes: 30, subcategories: [] },
  ],
  total_workouts: 6, total_minutes: 90,
};

test("categoryColors: цвет по имени (порядок Главной), служебная категория нейтральная", () => {
  const colors = categoryColors(dist, ["Ноги", "Тяга"]);
  assert.equal(colors.get("Ноги"), "var(--vp-cat-0)");
  assert.equal(colors.get("Тяга"), "var(--vp-cat-1)");
  assert.equal(colors.get("Другая активность"), NEUTRAL_COLOR);
});

test("categoryColors: порядок сортировки ответа не влияет на цвет, как и на Главной", () => {
  const order = ["Кор", "Тяга", "Ноги"];
  const reversed: AnalyticsDistributionV2 = { ...dist, categories: [...dist.categories].reverse() };
  const a = categoryColors(dist, order);
  const b = categoryColors(reversed, order);
  for (const name of ["Тяга", "Ноги", "Кор"]) {
    assert.equal(a.get(name), b.get(name));
    assert.equal(a.get(name), categoryColorVar(name, order));
  }
  assert.equal(a.get("Тяга"), "var(--vp-cat-1)");
});

test("categoryColors: категория вне Главной — стабильный хеш-цвет из палитры", () => {
  const first = categoryColors(dist, []).get("Кор");
  assert.equal(first, categoryColors(dist, ["X"]).get("Кор"));
  assert.match(first ?? "", /^var\(--vp-cat-[0-5]\)$/);
});

test("categoryColors: категории Главной с индексом ≥ 6 не совпадают по цвету с ранними (сдвиг к свободному)", () => {
  const order = ["А", "Б", "В", "Г", "Д", "Е", "Ж", "З"]; // Ж (6) и З (7) по модулю палитры = А и Б
  const big: AnalyticsDistributionV2 = {
    categories: order.map((name) => ({ name, workouts: 1, minutes: 10, subcategories: [] })),
    total_workouts: 8, total_minutes: 80,
  };
  const colors = categoryColors(big, order);
  const used = order.map((name) => colors.get(name));
  assert.equal(new Set(used).size, 6, "палитра из 6 цветов используется полностью");
  // ранние категории сохраняют свой цвет, как на Главной
  for (const name of order.slice(0, 6)) {
    assert.equal(colors.get(name), categoryColorVar(name, order));
  }
  // при ≤ 6 категориях с данными все цвета различны
  const six: AnalyticsDistributionV2 = { ...big, categories: big.categories.slice(0, 5).concat(big.categories[6]) };
  const sixColors = categoryColors(six, order);
  assert.equal(new Set(six.categories.map((c) => sixColors.get(c.name))).size, 6);
});

test("donutRings: внутреннее кольцо — категории без нулей, доли в сумме 1", () => {
  const { inner, outer, total } = donutRings(dist, "workouts");
  assert.equal(total, 6);
  assert.deepEqual(inner.map((s) => s.label), ["Тяга", "Кор", "Другая активность"]);
  assert.equal(inner[0].start, 0);
  assert.ok(Math.abs(inner[inner.length - 1].end - 1) < 1e-9);
  // внешнее: подкатегории Тяги (2 + 1 = все 3 тренировки категории — остатка нет), затем Кор и «Другая» целиком
  assert.deepEqual(outer.map((s) => s.label), ["Верт", "Гориз", "Кор", "Другая активность"]);
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

test("donutRings: минуты подкатегорий — остаток категории виден отдельным бледным сегментом", () => {
  const { outer } = donutRings(dist, "minutes");
  assert.deepEqual(outer.map((s) => [s.label, s.value]), [
    ["Верт", 40], ["Гориз", 5], ["Тяга", 5], ["Кор", 10], ["Другая активность", 30],
  ]);
  assert.ok(Math.abs(outer[outer.length - 1].end - 1) < 1e-9);
});

test("тренировки — только целые: дробь не показывается", () => {
  assert.equal(formatCount(2), "2");
  assert.equal(formatCount(0), "0");
  assert.equal(formatCount(0.5), "1"); // страховка: «0.5 тренировки» не рендерится никогда
  assert.equal(formatCount(1.5), "2");
  assert.ok(!/[.,]/.test(formatCount(2.4)));
  assert.equal(formatPercent(1, 4), "25%");
  assert.equal(formatPercent(1, 0), "0%");
});
