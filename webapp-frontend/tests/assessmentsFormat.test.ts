import assert from "node:assert/strict";
import { test } from "node:test";

import {
  bestValue, chartPoints, formatIsoDate, formatLastResult, formatValue, NOT_TESTED_TEXT, pathFor, validateResultForm,
} from "../src/assessmentsFormat.ts";

test("formatIsoDate / formatValue / formatLastResult", () => {
  assert.equal(formatIsoDate("2026-09-03"), "03.09.2026");
  assert.equal(formatValue("12", "повт."), "12 повт.");
  assert.equal(formatValue("12", ""), "12");
  assert.equal(formatLastResult(null), NOT_TESTED_TEXT);
  assert.equal(
    formatLastResult({ value: "42.5", unit: "сек", performed_on: "2026-09-03" }), "42.5 сек · 03.09.2026",
  );
});

const TODAY = "2026-10-02";
const ok = { performedOn: TODAY, value: "12", note: "" };

test("validateResultForm: валидные значения и нормализация", () => {
  assert.deepEqual(validateResultForm(ok, TODAY, true), { ok: true, performedOn: TODAY, value: 12, note: null });
  assert.deepEqual(
    validateResultForm({ ...ok, value: " 42,5 ", note: "  с резиной " }, TODAY, false),
    { ok: true, performedOn: TODAY, value: 42.5, note: "с резиной" },
  );
});

test("validateResultForm: ошибки", () => {
  const error = (patch: Partial<typeof ok>, integerOnly = true) => {
    const result = validateResultForm({ ...ok, ...patch }, TODAY, integerOnly);
    return result.ok ? null : result.error;
  };
  assert.equal(error({ performedOn: "" }), "Укажите дату");
  assert.equal(error({ performedOn: "2026-10-03" }), "Дата не может быть в будущем");
  assert.equal(error({ value: "" }), "Введите значение больше нуля");
  assert.equal(error({ value: "0" }), "Введите значение больше нуля");
  assert.equal(error({ value: "-1" }), "Введите значение больше нуля");
  assert.equal(error({ value: "abc" }), "Введите значение больше нуля");
  assert.equal(error({ value: "10000" }), "Слишком большое значение");
  assert.equal(error({ value: "10.5" }), "Повторения — целое число");
  assert.equal(error({ value: "10.555" }, false), "Не больше двух знаков после запятой");
  assert.equal(error({ note: "x".repeat(501) }), "Заметка не длиннее 500 символов");
});

test("chartPoints: границы, одна точка и плоская линия", () => {
  assert.deepEqual(chartPoints([], 100, 50, 5), []);
  assert.deepEqual(chartPoints([7], 100, 50, 5), [{ x: 50, y: 25 }]);
  assert.deepEqual(chartPoints([3, 3], 100, 50, 5), [{ x: 5, y: 25 }, { x: 95, y: 25 }]);
  // рост значения — вверх (меньший y); крайние точки у границ с отступом
  assert.deepEqual(chartPoints([10, 20], 100, 50, 5), [{ x: 5, y: 45 }, { x: 95, y: 5 }]);
});

test("pathFor и bestValue", () => {
  assert.equal(pathFor([{ x: 1, y: 2 }, { x: 3.14159, y: 4 }]), "M1.0,2.0 L3.1,4.0");
  assert.equal(bestValue([]), null);
  assert.equal(bestValue([3, 9, 5]), 9);
});
