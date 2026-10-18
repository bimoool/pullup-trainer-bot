import assert from "node:assert/strict";
import { test } from "node:test";

import {
  blockedReason, describeSchedule, electiveCounterLabel, isStartAllowed, normalizeBlockLetters, ordinalLabel,
  rowStatusLabel, rowSubtitle, weekOccurrenceTotal,
} from "../src/planRows.ts";

test("start_allowed is the single source of «Начать»", () => {
  assert.equal(isStartAllowed({ state: "available", start_allowed: false }), false);
  assert.equal(isStartAllowed({ state: "too_early", start_allowed: true }), true);
});

test("without start_allowed the state decides (old backend)", () => {
  for (const state of ["too_early", "infeasible", "completed", "missed"] as const) {
    assert.equal(isStartAllowed({ state }), false, state);
  }
  assert.equal(isStartAllowed({ state: "available" }), true);
  assert.equal(isStartAllowed({ state: null }), true);
  assert.equal(isStartAllowed({ state: "awaiting_assessment" }), true);
});

test("status labels, hand-written", () => {
  assert.equal(rowStatusLabel({ state: "too_early", available_from: "2026-10-21" }), "Доступно с 21 окт");
  assert.equal(rowStatusLabel({ state: "infeasible", start_allowed: false }), "Не уместится на этой неделе");
  assert.equal(rowStatusLabel({ state: "completed" }), "Выполнено");
  assert.equal(rowStatusLabel({ state: "available", start_allowed: true }), null);
  assert.equal(rowStatusLabel({ state: "available", start_allowed: false, blocked_reason: "no_access" }), "Нужна подписка");
  assert.equal(blockedReason({ state: "available", start_allowed: true }), null);
});

test("variant and ordinal wording", () => {
  assert.equal(rowSubtitle({ session_variant: "A", session_ordinal: 2 }, 3), "Объём (А) · занятие 2 из 3");
  assert.equal(rowSubtitle({ session_variant: "B", session_ordinal: 1 }, 2), "Сила (Б) · занятие 1 из 2");
  assert.equal(rowSubtitle({ session_variant: null, session_ordinal: null }, 2), null);
  assert.equal(ordinalLabel({ session_ordinal: 2 }, null), "занятие 2");
});

test("latin A/B become cyrillic only as standalone letters", () => {
  assert.equal(normalizeBlockLetters("A и B по очереди: объём, затем сила"), "А и Б по очереди: объём, затем сила");
  assert.equal(normalizeBlockLetters("Следующая тренировка B"), "Следующая тренировка Б");
  assert.equal(normalizeBlockLetters("BMI и ABC"), "BMI и ABC");
});

test("legacy schedule explanation (CONTRACT §5 fixture: 3 per week, capacity 2)", () => {
  const schedule = { sessions_per_week: 3, source: "catalogue", is_legacy: true, min_days_between_starts: 3, weekly_capacity: 2 } as const;
  const text = describeSchedule(schedule);
  assert.equal(text?.headline, "Расписание вашей версии курса: 3 занятия в неделю");
  assert.ok(text?.consequence?.includes("не больше 2"));
  assert.equal(text?.isLegacyThree, true);
  const fine = describeSchedule({ ...schedule, is_legacy: false, sessions_per_week: 2, weekly_capacity: 2 });
  assert.equal(fine?.headline, "Расписание курса: 2 занятия в неделю");
  assert.equal(fine?.consequence, null);
  assert.equal(describeSchedule(undefined), null);
});

test("occurrence total and elective counter", () => {
  const items = [
    { program_inclusion_id: 1, plan_week_id: 5, occurrence_index: 1 },
    { program_inclusion_id: 1, plan_week_id: 5, occurrence_index: 2 },
    { program_inclusion_id: 1, plan_week_id: 6, occurrence_index: 1 },
    { program_inclusion_id: null, plan_week_id: 5, occurrence_index: null },
  ];
  assert.equal(weekOccurrenceTotal(items, 1, 5), 2);
  assert.equal(electiveCounterLabel(1, 2), "Факультативы: 1 из 2 на этой неделе");
});
