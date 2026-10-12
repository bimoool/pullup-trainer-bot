import assert from "node:assert/strict";
import { test } from "node:test";

import {
  assistanceConfirmations, blockChecks, COURSE_INPUT_FIELDS, courseBlockName, courseInputsPayload, courseTargetText, describeCourseOutcome,
  describeOneRepMaxOutcome, describePendingInputs, describeSetupNeeds,
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

test("describeOneRepMaxOutcome: подтверждённым 1RM называется только оконченный тест с одиночным подходом", () => {
  assert.equal(
    describeOneRepMaxOutcome({ e1rm_kg: "15", conservative: false, outcome: "completed", confirmed: true, last_successful_single_kg: "15" }),
    "1RM: +15 кг",
  );
  assert.equal(describeOneRepMaxOutcome({ e1rm_kg: "52.5", conservative: true }), "1RM: +52.5 кг (консервативно)");
  assert.equal(
    describeOneRepMaxOutcome({ e1rm_kg: null, conservative: false, outcome: "completed", confirmed: false, last_successful_single_kg: null }),
    "Тест окончен и сохранён, но успешного одиночного подхода нет — 1RM не назначен.",
  );
  const stopped = describeOneRepMaxOutcome({
    e1rm_kg: null, conservative: false, outcome: "stopped", confirmed: false, last_successful_single_kg: "15",
  });
  assert.ok(stopped.includes("остановлен") && stopped.includes("+15 кг") && stopped.includes("не подтверждённый 1RM"));
  assert.ok(!stopped.startsWith("1RM"));
  const stoppedEarly = describeOneRepMaxOutcome({
    e1rm_kg: null, conservative: false, outcome: "stopped", confirmed: false, last_successful_single_kg: null,
  });
  assert.ok(stoppedEarly.includes("успешного одиночного подхода не было"));
});

test("courseBlockName: названия объёма/силы из снимка сессии, без выдумки", () => {
  const snapshot = {
    provenance: {
      course_program: {
        blocks: [{ block_role: "a_volume" }, { block_role: "a_weighted_strength" }],
      },
    },
  };
  assert.equal(courseBlockName(snapshot, 0), "Объём A");
  assert.equal(courseBlockName(snapshot, 1), "Сила A (5×5)");
  assert.equal(courseBlockName(snapshot, 2), null);
  assert.equal(courseBlockName(null, 0), null);
  assert.equal(courseBlockName({ provenance: { strategy: "step" } }, 0), null);
  assert.equal(courseBlockName({ provenance: { course_program: { blocks: [{ block_role: "mystery" }] } } }, 0), null);
});

test("describeSetupNeeds: зачем помощь/вес — по правилам допуска, без выдуманной резины и килограммов", () => {
  const assisted = describeSetupNeeds(["volume_capacity", "volume_assistance", "strength_assistance"]).join(" ");
  assert.match(assisted, /меньше 10/);
  assert.match(assisted, /не подбирает ни резину, ни её усилие/);
  assert.match(assisted, /модель, цвет, крепление и положение/);
  const weighted = describeSetupNeeds(["one_rep_max", "load_step"]).join(" ");
  assert.match(weighted, /Допуск к работе с весом получен/);
  assert.match(weighted, /1RM/);
  assert.match(weighted, /Вес не назначается/);
  for (const text of [assisted, weighted]) {
    assert.doesNotMatch(text, /\d+(?:[.,]\d+)?\s?кг/); // ни одного конкретного значения веса/резины
  }
  const pending = describeSetupNeeds(["assistance_confirmation"], [{ block: "volume_a", intent: "decrease_assistance" }]);
  assert.equal(pending.length, 1);
  assert.match(pending[0], /уменьшить помощь/);
  assert.deepEqual(describeSetupNeeds(["fresh_max", "body_mass"]), []);
});
