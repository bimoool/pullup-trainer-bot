import assert from "node:assert/strict";
import { test } from "node:test";

import type { PrescriptionBlockV2, WorkoutItemResponseV2, WorkoutResponseV2 } from "../src/apiV2.ts";
import { firstPrescriptionDescription, itemPrescriptionLine, v1BlockKey } from "../src/prescriptionFormat.ts";
import { summarizeProtocol } from "../src/protocolConfig.ts";
import { formatItemSummary } from "../src/workoutDetailFormat.ts";

// Фикстуры — ответ GET /api/v2/workouts/{id} свежей установки (`alembic upgrade head`, сид
// a4c8e1f7b2d9 + b7d2e9f4a1c3): строка complex_items 2 / упражнение 7 → блок `i2e7` (W-лесенка),
// строка 1 / упражнение 7 → `i1e7` («Максимум подтягиваний»). Ключ — i<item.id>e<item.exercise_id>
// (#303 review B3; app/domain/workout_definition.py::v1_block_key).

const LADDER = [5, 4, 3, 2, 1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5];
const W_SEQUENCE = "5-4-3-2-1-2-3-4-5-4-3-2-1-2-3-4-5";
const EXERCISE = { id: 7, display_name: "Подтягивания" };

const wLadderItem: WorkoutItemResponseV2 = {
  id: 2, exercise_id: 7, exercise_name: "Подтягивания", order_index: 0,
  protocol: { type: "reps_sets", prescription: { reps: 3, sets: 17, source: "static" }, rest_seconds: 10 },
};
const wLadderBlock: PrescriptionBlockV2 = {
  key: "i2e7", exercise: EXERCISE, kind: "sets", description: W_SEQUENCE, rest_description: "отдых 0:10",
  prep_seconds: 5, rest_after_block_seconds: null, total_target_reps: 53,
  sets: LADDER.map((reps, i) => ({
    kind: "reps", target_reps: reps, target_seconds: null,
    rest_after_seconds: i === LADDER.length - 1 ? null : 10, role: "working",
  })),
  interval: null,
};
const wLadder: WorkoutResponseV2 = {
  id: 2, title: "W-лесенка", source_type: "system", owner_user_id: null, items: [wLadderItem],
  current_version: { id: 4, version_no: 2, content_hash: "9cb44e16a2e25436dad353c06f43683606bd574bcf403d1455c42941bfe0260c" },
  prescription: [wLadderBlock],
};

const maxItem: WorkoutItemResponseV2 = {
  id: 1, exercise_id: 7, exercise_name: "Подтягивания", order_index: 0,
  protocol: { type: "max_effort", prescription: { source: "static", attempts: 4 }, rest_seconds: 120 },
};
const maxBlock: PrescriptionBlockV2 = {
  key: "i1e7", exercise: EXERCISE, kind: "sets", description: "Максимум × 4",
  rest_description: "отдых 3:00 → 2:00 → 1:00", prep_seconds: 5, rest_after_block_seconds: null,
  total_target_reps: null,
  sets: [180, 120, 60, null].map((rest) => ({
    kind: "max_reps", target_reps: null, target_seconds: null, rest_after_seconds: rest, role: "max",
  })),
  interval: null,
};
const maximum: WorkoutResponseV2 = {
  id: 1, title: "Максимум подтягиваний", source_type: "system", owner_user_id: null, items: [maxItem],
  current_version: { id: 2, version_no: 2, content_hash: "8a9ec1d5bad7ef4ab923aef4db309b3eaf548510d9ef2e05923d5146fdebb496" },
  prescription: [maxBlock],
};

// Ровно те выражения, что строят строку строки упражнения на экранах (WorkoutDetailScreen,
// SessionPreScreen): v2-рецепт, а при его отсутствии — V1-сводка.
const detailLine = (workout: WorkoutResponseV2, item: WorkoutItemResponseV2) =>
  itemPrescriptionLine(workout, item) ?? formatItemSummary(item.protocol);
const preScreenLine = (workout: WorkoutResponseV2, item: WorkoutItemResponseV2) =>
  itemPrescriptionLine(workout, item) ?? summarizeProtocol(item.protocol).lines[0];

test("ключ блока — канонический i<item.id>e<item.exercise_id>, как у бэкенда", () => {
  assert.equal(v1BlockKey(wLadderItem), "i2e7");
  assert.equal(v1BlockKey(maxItem), "i1e7");
});

test("R1: W-лесенка (item 2, exercise 7, ключ i2e7) находит v2-рецепт, а не null", () => {
  assert.equal(itemPrescriptionLine(wLadder, wLadderItem), `${W_SEQUENCE} · отдых 0:10`);
  assert.equal(firstPrescriptionDescription(wLadder), W_SEQUENCE);
});

test("R1: Detail W-лесенки показывает явную последовательность, не V1 «17 × 3»", () => {
  // без исправления (ключ `i2`) строка уходила в V1-сводку:
  assert.equal(formatItemSummary(wLadderItem.protocol), "17 × 3 повторения · отдых 10 сек");
  assert.equal(detailLine(wLadder, wLadderItem), `${W_SEQUENCE} · отдых 0:10`);
  assert.doesNotMatch(detailLine(wLadder, wLadderItem), /17 × 3/);
});

test("R1: пре-скрин W-лесенки — тот же v2-рецепт, не «17 × 3 повторения»", () => {
  assert.equal(summarizeProtocol(wLadderItem.protocol).lines[0], "17 × 3 повторения");
  assert.equal(preScreenLine(wLadder, wLadderItem), `${W_SEQUENCE} · отдых 0:10`);
});

test("R1: «Максимум подтягиваний» (i1e7) — поподходный отдых 3:00 → 2:00 → 1:00, не сплющенный V1", () => {
  assert.equal(formatItemSummary(maxItem.protocol), "4 попытки на максимум · отдых 2:00");
  assert.equal(detailLine(maximum, maxItem), "Максимум × 4 · отдых 3:00 → 2:00 → 1:00");
  assert.equal(preScreenLine(maximum, maxItem), "Максимум × 4 · отдых 3:00 → 2:00 → 1:00");
});

test("несовпадающая пара item/exercise не подхватывает чужой блок", () => {
  // та же строка, но упражнение сменилось (новый блок i2e9 ещё не в рецепте) — не блок i2e7
  assert.equal(itemPrescriptionLine(wLadder, { id: 2, exercise_id: 9 }), null);
  // то же упражнение, другая строка — не блок i2e7
  assert.equal(itemPrescriptionLine(wLadder, { id: 1, exercise_id: 7 }), null);
  // ключи-префиксы не путаются: строка 1 / упражнение 7 ≠ строка 1 / упражнение 77, ≠ строка 12 / упр. 7
  const prefixes: WorkoutResponseV2 = {
    ...wLadder, prescription: [{ ...wLadderBlock, key: "i1e77" }, { ...wLadderBlock, key: "i12e7", description: "12/7" }],
  };
  assert.equal(itemPrescriptionLine(prefixes, { id: 1, exercise_id: 7 }), null);
  assert.equal(itemPrescriptionLine(prefixes, { id: 12, exercise_id: 7 }), "12/7 · отдых 0:10");
  // устаревший формат ключа без упражнения больше не совпадает
  assert.equal(itemPrescriptionLine({ prescription: [{ ...wLadderBlock, key: "i2" }] }, wLadderItem), null);
});

test("нет версии или блока — null (экран показывает V1-сводку)", () => {
  assert.equal(itemPrescriptionLine({ prescription: null }, wLadderItem), null);
  assert.equal(itemPrescriptionLine({}, wLadderItem), null);
  assert.equal(detailLine({ ...wLadder, prescription: null }, wLadderItem), "17 × 3 повторения · отдых 10 сек");
  assert.equal(firstPrescriptionDescription({ prescription: [] }), null);
});
