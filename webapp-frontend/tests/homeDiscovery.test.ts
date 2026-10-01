import assert from "node:assert/strict";
import { test } from "node:test";

import { collectCategories, groupProgramsByCategory, searchContent } from "../src/homeDiscovery.ts";

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
