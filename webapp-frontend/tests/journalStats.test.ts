import assert from "node:assert/strict";
import { test } from "node:test";

import { journalEntryTitle } from "../src/journalFormat.ts";
import { journalCardStats } from "../src/journalStats.ts";

function log(set_number: number, value: string, unit = "reps") {
  return { set_number, is_max_set: false, metric_type: "x", value, unit, effort: null, note: null };
}
function block(order_index: number, set_logs: ReturnType<typeof log>[], extra: Record<string, unknown> = {}) {
  return { order_index, set_logs, result: null, protocol_type: null, ...extra };
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const s = (blocks: any[], effort: string | null = null, extra: Record<string, unknown> = {}) =>
  journalCardStats({ blocks, effort, ...extra });
const flat = (stats: ReturnType<typeof s>) => stats.map((x) => `${x.label}=${x.value}`);

test("journalCardStats: силовая — подходы, сумма повторов, усилие с цветом", () => {
  const stats = s([block(0, [log(1, "8.00"), log(2, "7.00")])], "4.0");
  assert.deepEqual(flat(stats), ["Подходы=2", "Повторы=15", "Усилие=4"]);
  assert.equal(stats[2].effort, 4);
});

test("journalCardStats: многоблочная запись агрегирует суммы по блокам", () => {
  const stats = s([block(0, [log(1, "8"), log(2, "7")]), block(1, [log(1, "22", "reps"), log(2, "20")])]);
  assert.deepEqual(flat(stats), ["Подходы=4", "Повторы=57", "Усилие=—"]);
  assert.equal(stats[2].effort, null);
});

test("journalCardStats: подходы по времени — вместо повторов суммарное время", () => {
  assert.deepEqual(flat(s([block(0, [log(1, "30", "s"), log(2, "25", "s")])])), ["Подходы=2", "Время=0:55", "Усилие=—"]);
});

test("journalCardStats: только интервалы — число интервалов и фактическое время", () => {
  const interval = block(0, [], {
    protocol_type: "interval",
    result: { type: "interval", actual_duration_seconds: 15, completed_cycles: 2 },
  });
  assert.deepEqual(flat(s([interval], "3")), ["Интервалы=2", "Время=0:15", "Усилие=3"]);
});

test("journalCardStats: пустая запись — прочерки", () => {
  assert.deepEqual(flat(s([])), ["Подходы=—", "Повторы=—", "Усилие=—"]);
});

test("journalCardStats: активность — длительность ч:мм, дистанция «—»", () => {
  const stats = s([], "3", { activity_type: "swimming", duration_seconds: 4500 });
  assert.deepEqual(flat(stats), ["Длительность=1:15", "Дистанция=—", "Усилие=3"]);
  assert.deepEqual(flat(s([], null, { activity_type: "yoga", duration_seconds: null })), ["Длительность=—", "Дистанция=—", "Усилие=—"]);
});

test("journalEntryTitle: заголовок бэкенда; у факультатива без заголовка — имя первого блока; иначе «Тренировка»", () => {
  const named = block(0, [log(1, "5")], { exercise_name: "Факультатив — 3 минуты подтягиваний", set_targets: [], interval_config: null });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const t = (title: string | null, source: string, blocks: any[]) => journalEntryTitle({ title, source, blocks });
  assert.equal(t("Моя силовая", "plan", [named]), "Моя силовая");
  assert.equal(t(null, "elective", [named]), "Факультатив — 3 минуты подтягиваний");
  assert.equal(t(null, "elective", []), "Тренировка");
  assert.equal(t(null, "plan", [named]), "Тренировка");
});
