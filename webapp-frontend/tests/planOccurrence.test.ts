// issue #304 — одна строка плана = одно занятие: подписи состояний, выбор занятия для старта,
// разбор объёма своего плана по неделям (0 допустим).
import assert from "node:assert/strict";
import { test } from "node:test";

import { parseWeekVolumes } from "../src/customPlanFormat.ts";
import { nextOccurrenceId, occurrenceStateLabel, weekProgress } from "../src/planWeekNav.ts";

test("occurrenceStateLabel: «рано» с датой, «не успеть», «пропущено»; доступно/сделано — без подписи", () => {
  assert.equal(occurrenceStateLabel({ state: "too_early", available_from: "2026-10-08" }), "Доступно с 8 окт");
  assert.equal(occurrenceStateLabel({ state: "infeasible" }), "Не успеть на этой неделе");
  assert.equal(occurrenceStateLabel({ state: "missed" }), "Пропущено");
  assert.equal(occurrenceStateLabel({ state: "available" }), null);
  assert.equal(occurrenceStateLabel({ state: "completed" }), null);
  assert.equal(occurrenceStateLabel({}), null);
});

const items = [
  { id: 10, program_inclusion_id: 1, plan_week_id: 5, occurrence_index: 1, state: "completed" },
  { id: 12, program_inclusion_id: 1, plan_week_id: 5, occurrence_index: 3, state: "infeasible" },
  { id: 11, program_inclusion_id: 1, plan_week_id: 5, occurrence_index: 2, state: "too_early" },
  { id: 20, program_inclusion_id: 1, plan_week_id: 6, occurrence_index: 1, state: "available" },
  { id: 30, program_inclusion_id: null, plan_week_id: 5, occurrence_index: 1, state: "available" },
];

test("nextOccurrenceId: первое незасчитанное занятие курса своей недели; не «не успеть», если есть другое", () => {
  assert.equal(nextOccurrenceId(items, 1, 5), 11);
  assert.equal(nextOccurrenceId(items, 1, 6), 20);
  assert.equal(nextOccurrenceId(items, 1, 7), null);
  assert.equal(nextOccurrenceId([items[1]], 1, 5), 12);
});

test("weekProgress: занятия — по одной группе, «N из M» без скрытого множителя", () => {
  const occurrences = [
    { count_per_week: 1, done_count: 1 }, { count_per_week: 1, done_count: 0 }, { count_per_week: 1, done_count: 0 },
  ];
  assert.deepEqual(weekProgress(occurrences.map((item) => [item])), { done: 1, total: 3 });
});

test("parseWeekVolumes: 2/2/0/2/2/0 — ровно этот вектор, 0 — пустая неделя", () => {
  assert.deepEqual(parseWeekVolumes("2 2 0 2 2 0"), { weeks: [2, 2, 0, 2, 2, 0], error: null });
  assert.deepEqual(parseWeekVolumes("2,2,0, 2"), { weeks: [2, 2, 0, 2], error: null });
  assert.notEqual(parseWeekVolumes("0 0").error, null);
  assert.notEqual(parseWeekVolumes("2 x").error, null);
  assert.notEqual(parseWeekVolumes("15").error, null);
  assert.notEqual(parseWeekVolumes("").error, null);
});
