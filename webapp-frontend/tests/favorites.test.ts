import assert from "node:assert/strict";
import { test } from "node:test";

import { favoritesRowMode, isFavorite } from "../src/favorites.ts";
import { searchContent } from "../src/homeDiscovery.ts";

const fav = (target_type: "workout" | "program", target_id: number) => ({
  target_type, target_id, title: "x", subtitle: null,
});

test("isFavorite: различает тип и id", () => {
  const list = [fav("workout", 1), fav("program", 2)];
  assert.equal(isFavorite(list, "workout", 1), true);
  assert.equal(isFavorite(list, "program", 1), false);
  assert.equal(isFavorite(list, "program", 2), true);
  assert.equal(isFavorite([], "workout", 1), false);
});

test("favoritesRowMode: элементы / подсказка только новичку / скрыт", () => {
  assert.equal(favoritesRowMode(2, true), "items");
  assert.equal(favoritesRowMode(2, false), "items");
  assert.equal(favoritesRowMode(0, false), "hint");
  assert.equal(favoritesRowMode(0, true), "hidden");
});

test("searchContent: чип «Избранное» оставляет только избранные программы и тренировки", () => {
  const data = {
    programs: [
      { id: 1, name: "А", goal: "", structure_type: "recurring", category: null, progression_strategy_type: null },
      { id: 2, name: "Б", goal: "", structure_type: "recurring", category: null, progression_strategy_type: null },
    ],
    workouts: [
      { id: 1, title: "Т1", source_type: "user", owner_user_id: 1, items: null },
      { id: 2, title: "Т2", source_type: "user", owner_user_id: 1, items: null },
    ],
    exercises: [{ id: 1, name: "Упр", metric_type: "reps", category: "c", subcategory: null }],
  };
  const all = searchContent(data, "", null, null);
  assert.equal(all.total, 5);
  const only = searchContent(data, "", null, [fav("program", 2), fav("workout", 1)]);
  assert.deepEqual(only.programs.map((p) => p.id), [2]);
  assert.deepEqual(only.workouts.map((w) => w.id), [1]);
  assert.equal(only.exercises.length, 0);
  assert.equal(searchContent(data, "", null, []).total, 0);
});
