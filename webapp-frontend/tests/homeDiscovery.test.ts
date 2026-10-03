import assert from "node:assert/strict";
import { test } from "node:test";

import {
  categoryColorVar, collectCategories, groupProgramsByCategory, homeCategoryOrder, programCategoryColorVar,
  searchContent, toggleSearchFilter,
} from "../src/homeDiscovery.ts";

const program = (id: number, name: string, category: string | null) => ({
  id, name, goal: `цель ${name}`, structure_type: "recurring", category, progression_strategy_type: null,
});
const exercise = (id: number, name: string, category: string) => ({
  id, name, metric_type: "reps", category, subcategory: null,
});
const workout = (id: number, title: string) => ({ id, title, source_type: "user", owner_user_id: 1, items: null });

const programs = [program(1, "Сила", "strength"), program(2, "Без", null), program(3, "Гибкость", "mobility"), program(4, "Мощь", "strength")];
const exercises = [exercise(1, "Подтягивания", "strength"), exercise(2, "Шпагат", "mobility")];
const workouts = [workout(1, "Утренняя")];

test("groupProgramsByCategory: ряды по категории, «Другое» последним", () => {
  const rows = groupProgramsByCategory(programs);
  assert.deepEqual(rows.map((r) => r.category), ["strength", "mobility", "Другое"]);
  assert.deepEqual(rows[0].programs.map((p) => p.id), [1, 4]);
  assert.deepEqual(rows[2].programs.map((p) => p.id), [2]);
});

test("collectCategories: только реальные значения", () => {
  assert.deepEqual(collectCategories(programs, exercises), ["mobility", "strength"]);
});

test("searchContent: подстрока без регистра, группы, счётчик", () => {
  const all = searchContent({ programs, workouts, exercises }, "", null);
  assert.equal(all.total, 4 + 1 + 2);
  const hit = searchContent({ programs, workouts, exercises }, "  ПОДТЯГ ", null);
  assert.equal(hit.total, 1);
  assert.equal(hit.exercises[0].name, "Подтягивания");
  assert.equal(searchContent({ programs, workouts, exercises }, "zzz", null).total, 0);
});

test("searchContent: фильтр категории скрывает тренировки и чужие категории", () => {
  const res = searchContent({ programs, workouts, exercises }, "", "mobility");
  assert.deepEqual(res.programs.map((p) => p.id), [3]);
  assert.equal(res.workouts.length, 0);
  assert.deepEqual(res.exercises.map((e) => e.id), [2]);
});

const assessments = [
  { id: 1, name: "Максимум подтягиваний", description: "Сколько раз за один подход", metric_type: "reps", unit: "повт.", last_result: null, results_count: 0, trend: [] },
  { id: 2, name: "Вис на перекладине", description: null, metric_type: "time", unit: "сек", last_result: null, results_count: 0, trend: [] },
];

test("searchContent: тесты — отдельная группа, ищутся по названию и описанию (#281, D6)", () => {
  const data = { programs, workouts, exercises, assessments };
  const all = searchContent(data, "", null);
  assert.deepEqual(all.tests.map((t) => t.id), [1, 2]);
  assert.equal(all.total, 4 + 1 + 2 + 2);
  assert.deepEqual(searchContent(data, "ВИС", null).tests.map((t) => t.id), [2]);
  assert.deepEqual(searchContent(data, "один подход", null).tests.map((t) => t.id), [1]);
  // без assessments (сбой загрузки) группа пуста, остальной поиск работает
  assert.equal(searchContent({ programs, workouts, exercises }, "", null).tests.length, 0);
});

test("searchContent: чип «Тесты» оставляет только тесты; категория/избранное тесты скрывают", () => {
  const data = { programs, workouts, exercises, assessments };
  const only = searchContent(data, "", null, null, true);
  assert.equal(only.programs.length + only.workouts.length + only.exercises.length, 0);
  assert.equal(only.total, 2);
  assert.equal(searchContent(data, "", "strength").tests.length, 0);
  assert.equal(searchContent(data, "", null, []).tests.length, 0);
});

test("toggleSearchFilter: «Тесты» взаимоисключающе с «Избранным» и категорией (#284 C3)", () => {
  const base = { query: "", category: null as string | null, favoritesOnly: false, testsOnly: false };
  // «Тесты» сбрасывает избранное и категорию
  const withBoth = { ...base, category: "strength", favoritesOnly: true };
  assert.deepEqual(toggleSearchFilter(withBoth, { kind: "tests" }), { ...base, testsOnly: true });
  // избранное и категория сбрасывают «Тесты»
  const tests = { ...base, testsOnly: true };
  assert.deepEqual(toggleSearchFilter(tests, { kind: "favorites" }), { ...base, favoritesOnly: true });
  assert.deepEqual(toggleSearchFilter(tests, { kind: "category", category: "mobility" }), { ...base, category: "mobility" });
  // повторное нажатие снимает чип; «Избранное» + категория по-прежнему сочетаются
  assert.deepEqual(toggleSearchFilter(tests, { kind: "tests" }), base);
  const fav = toggleSearchFilter(base, { kind: "favorites" });
  assert.deepEqual(toggleSearchFilter(fav, { kind: "category", category: "strength" }), { ...base, favoritesOnly: true, category: "strength" });
  assert.equal(toggleSearchFilter(withBoth, { kind: "category", category: "strength" }).category, null);
  // состояние, недостижимое через чипы, больше не получается: «Тесты» + категория
  const data = { programs, workouts, exercises, assessments };
  const state = toggleSearchFilter(toggleSearchFilter(base, { kind: "category", category: "strength" }), { kind: "tests" });
  const res = searchContent(data, "", state.category, state.favoritesOnly ? [] : null, state.testsOnly);
  assert.deepEqual(res.tests.map((t) => t.id), [1, 2]);
});

test("categoryColorVar: цвет — функция имени, Главная и Планы совпадают с порядком рядов", () => {
  const order = homeCategoryOrder(programs);
  assert.deepEqual(order, ["strength", "mobility", "Другое"]);
  assert.equal(categoryColorVar("strength", order), "var(--vp-cat-0)");
  assert.equal(categoryColorVar("mobility", order), "var(--vp-cat-1)");
  assert.equal(programCategoryColorVar(programs, 3), categoryColorVar("mobility", order));
  assert.equal(programCategoryColorVar(programs, 2), categoryColorVar("Другое", order));
  assert.equal(programCategoryColorVar(programs, 99), null);
  // не из рядов Главной: стабильный хеш, не зависит от порядка
  assert.equal(categoryColorVar("unknown", order), categoryColorVar("unknown", [...order].reverse().concat("x")));
  assert.match(categoryColorVar("unknown", order), /^var\(--vp-cat-[0-5]\)$/);
});
