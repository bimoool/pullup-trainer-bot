import assert from "node:assert/strict";
import { test } from "node:test";

import {
  categoryColorVar, categoryKey, categoryLabel, collectCategories, groupProgramsByCategory, homeCategoryOrder, programCategoryColorVar,
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
  assert.deepEqual(rows.map((r) => r.category), ["strength", "mobility", ""]); // внутренние ключи
  assert.deepEqual(rows.map((r) => r.label), ["strength", "mobility", "Другое"]); // подписи для показа
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
  assert.deepEqual(order, ["strength", "mobility", ""]);
  assert.equal(categoryColorVar("strength", order), "var(--vp-cat-0)");
  assert.equal(categoryColorVar("mobility", order), "var(--vp-cat-1)");
  assert.equal(programCategoryColorVar(programs, 3), categoryColorVar("mobility", order));
  assert.equal(programCategoryColorVar(programs, 2), categoryColorVar("", order));
  assert.equal(programCategoryColorVar(programs, 99), null);
  // не из рядов Главной: стабильный хеш, не зависит от порядка
  assert.equal(categoryColorVar("unknown", order), categoryColorVar("unknown", [...order].reverse().concat("x")));
  assert.match(categoryColorVar("unknown", order), /^var\(--vp-cat-[0-5]\)$/);
});

test("categoryLabel: слаги каталога — человеческие подписи, а не pull_ups/PULL_UPS", () => {
  assert.equal(categoryLabel("pull_ups"), "Подтягивания");
  assert.equal(categoryLabel("PULL_UPS"), "Подтягивания");
  assert.equal(categoryLabel("general_fitness"), "Общая физическая подготовка");
  assert.equal(categoryLabel("Подтягивания"), "Подтягивания");
  assert.equal(categoryLabel("some_new_slug"), "Some new slug");
  assert.equal(categoryLabel(null), "Другое");
  assert.equal(categoryLabel("  "), "Другое");
});

test("слаг программы и подпись упражнения — одна категория: ряд, чип, фильтр", () => {
  const slugPrograms = [program(1, "Подтягивания", "pull_ups")];
  const labelled = [exercise(1, "Подтягивания с резиной", "Подтягивания")];
  assert.deepEqual(groupProgramsByCategory(slugPrograms).map((r) => [r.category, r.label]), [["pull_ups", "Подтягивания"]]);
  assert.deepEqual(collectCategories(slugPrograms, labelled), ["pull_ups"]); // один ключ, один чип
  const hit = searchContent({ programs: slugPrograms, workouts: [], exercises: labelled }, "", "pull_ups");
  assert.equal(hit.programs.length, 1);
  assert.equal(hit.exercises.length, 1);
  // цвет категории не зависит от того, слаг пришёл или подпись (Аналитика отдаёт слаг)
  assert.equal(categoryColorVar("pull_ups", homeCategoryOrder(slugPrograms)), categoryColorVar("Подтягивания", homeCategoryOrder(slugPrograms)));
});

test("ключ ≠ подпись: разные категории не сливаются, каждая со своим рядом, фильтром и ключом «Все ›»", () => {
  const rows = [
    program(1, "A", "e2e_sweep"), program(2, "B", "E2E_Sweep"), program(3, "C", "e2e_discovery_strength"),
    program(4, "D", "e2e_discovery_mobility"), program(5, "E", "pull_ups"), program(6, "F", "Подтягивания"),
  ];
  const grouped = groupProgramsByCategory(rows);
  // e2e_sweep и E2E_Sweep — разные ключи (даже при одинаковой человеческой подписи); pull_ups = Подтягивания (сид)
  assert.deepEqual(grouped.map((r) => r.category), [
    "e2e_sweep", "E2E_Sweep", "e2e_discovery_strength", "e2e_discovery_mobility", "pull_ups",
  ]);
  assert.deepEqual(grouped.find((r) => r.category === "pull_ups")?.programs.map((p) => p.id), [5, 6]);
  assert.equal(grouped[0].label, "E2e sweep");
  assert.equal(grouped[2].label, "E2e discovery strength");
  // фильтр по ключу показывает только свою категорию
  const only = searchContent({ programs: rows, workouts: [], exercises: [] }, "", "e2e_sweep");
  assert.deepEqual(only.programs.map((p) => p.id), [1]);
  const mobility = searchContent({ programs: rows, workouts: [], exercises: [] }, "", "e2e_discovery_mobility");
  assert.deepEqual(mobility.programs.map((p) => p.id), [4]);
  // чипы поиска — ключи, различимы даже при совпавшей подписи
  assert.deepEqual(collectCategories(rows, []).sort(), ["E2E_Sweep", "e2e_discovery_mobility", "e2e_discovery_strength", "e2e_sweep", "pull_ups"].sort());
  // в подписи технический слаг не виден
  for (const row of grouped) {
    assert.doesNotMatch(row.label, /_/);
  }
  assert.equal(categoryKey("  PULL_UPS "), "pull_ups");
  assert.equal(categoryKey(null), "");
});
