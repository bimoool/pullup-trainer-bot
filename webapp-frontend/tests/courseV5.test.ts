import assert from "node:assert/strict";
import { test } from "node:test";

import {
  assistanceConfirmations, blockChecks, COURSE_INPUT_FIELDS, courseInputsPayload, courseTargetText, describeCourseOutcome,
  describePendingInputs,
} from "../src/courseV5.ts";

test("courseTargetText: маркеры V5.6", () => {
  assert.equal(courseTargetText({ value: "17", marker: "amrap" }), "Максимум чистых, не меньше 17");
  assert.equal(courseTargetText({ value: "5", marker: "control", cap_reps: 8 }), "Цель: 5–8, не больше 8");
  assert.equal(courseTargetText({ value: "5", marker: "dynamic" }), "Цель: 5; 2 и меньше — блок окончен");
  assert.equal(courseTargetText({ value: "5.00", marker: "working" }), "Цель: 5");
  assert.equal(courseTargetText({ value: "3" }), null);
  assert.equal(courseTargetText(null), null);
});

test("blockChecks: неотмеченное — неизвестно (null), никогда не false/true", () => {
  assert.deepEqual(blockChecks([{ technique: true, rest: false }, { technique: false, rest: true }]), [
    { block_index: 0, technique_valid: true, rest_within_limit: null },
    { block_index: 1, technique_valid: null, rest_within_limit: true },
  ]);
});

test("describeCourseOutcome: типизированные итоги блоков", () => {
  assert.equal(
    describeCourseOutcome({ block_role: "a_weighted_strength", decision: "increase_load", details: { delta_kg: "1.5" } }),
    "Сила A (5×5): вес растёт (+1.5 кг)",
  );
  assert.equal(
    describeCourseOutcome({ block_role: "b_volume", decision: "hold", reason: "plan_not_closed", details: { intermediate_goal: 60 } }),
    "Объём B: ступень повторяется; в следующий раз — не меньше 60 — план не закрыт",
  );
  assert.equal(
    describeCourseOutcome({ block_role: "a_volume", decision: "repeat", reason: "unconfirmed" }),
    "Объём A: план повторяется — техника не подтверждена",
  );
});

test("describePendingInputs", () => {
  assert.equal(describePendingInputs(["one_rep_max", "load_step"]), "тест 1RM (или ваш недавний результат 5×5 / 5×3), шаг дополнительного веса");
});

test("courseInputsPayload: только заполненное, резина однозначно, без помощи — явно", () => {
  const empty = { bodyweight: false, name: "", colour: "", attachment: "", body_position: "" };
  assert.deepEqual(courseInputsPayload({ known_strength_a_kg: "20", load_step_kg: "1,25", fresh_max: "" }, {}, false), {
    known_strength_a_kg: "20", load_step_kg: "1.25",
  });
  assert.deepEqual(
    courseInputsPayload(
      { volume_capacity: "10" },
      {
        volume: { ...empty, name: "Синяя", colour: "синяя", attachment: "петля", body_position: "стопа" },
        strength: { ...empty, bodyweight: true },
      },
      true,
    ),
    {
      volume_capacity: 10,
      volume_assistance: { kind: "band", name: "Синяя", colour: "синяя", attachment: "петля", body_position: "стопа" },
      strength_assistance: { kind: "bodyweight" },
      clear_recovery_check: true,
    },
  );
  assert.deepEqual(courseInputsPayload({}, { volume: empty }, false), {}); // резина без названия не угадывается
  // Неполная резина (нет цвета/положения) не отправляется как готовая.
  assert.deepEqual(courseInputsPayload({}, { volume: { ...empty, name: "Синяя", attachment: "петля" } }, false), {});
});

test("assistanceConfirmations: только полные записи или «без помощи»", () => {
  const empty = { bodyweight: false, name: "", colour: "", attachment: "", body_position: "" };
  assert.deepEqual(
    assistanceConfirmations([
      { block: "strength_a", fields: { ...empty, name: "Жёлтая" } },
      { block: "volume_a", fields: { bodyweight: false, name: "Красная", colour: "красная", attachment: "петля", body_position: "колено" } },
      { block: "strength_b", fields: { ...empty, bodyweight: true } },
    ]),
    [
      { block: "volume_a", setup: { kind: "band", name: "Красная", colour: "красная", attachment: "петля", body_position: "колено" } },
      { block: "strength_b", setup: { kind: "bodyweight" } },
    ],
  );
});

test("1RM вручную не вводится: только тест в приложении или заявленные 5×5 / 5×3", () => {
  const keys = Object.values(COURSE_INPUT_FIELDS).flat().map((field) => field.key);
  assert.ok(!keys.includes("e1rm_kg"));
  assert.deepEqual(COURSE_INPUT_FIELDS.one_rep_max.map((field) => field.key), ["known_strength_a_kg", "known_strength_b_kg"]);
});
