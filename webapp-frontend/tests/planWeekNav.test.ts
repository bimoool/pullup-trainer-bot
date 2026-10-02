import assert from "node:assert/strict";
import { test } from "node:test";

import {
  canAdvanceWeek, currentWeekIndex, groupCounter, isEditableWeek, localToday, resolveCurrentWeekId,
  resolveCurrentWeekIndex, stepWeek, weekProgress, weekRangeLabel,
} from "../src/planWeekNav.ts";

test("weekRangeLabel: через границу месяца и года", () => {
  assert.equal(weekRangeLabel("2026-09-29"), "29 сен – 5 окт");
  assert.equal(weekRangeLabel("2026-12-28"), "28 дек – 3 янв");
});

test("currentWeekIndex: последняя начавшаяся неделя; все в будущем → первая", () => {
  const weeks = [
    { id: 1, start_date: "2026-09-15" }, { id: 2, start_date: "2026-09-22" },
    { id: 3, start_date: "2026-09-29" }, { id: 4, start_date: "2026-10-06" },
  ];
  assert.equal(currentWeekIndex(weeks, "2026-10-01"), 2);
  assert.equal(currentWeekIndex(weeks, "2026-09-29"), 2);
  assert.equal(currentWeekIndex(weeks, "2026-09-01"), 0);
});

test("stepWeek: ‹ и › упираются в края списка", () => {
  assert.equal(stepWeek(2, -1, 3), 1);
  assert.equal(stepWeek(0, -1, 3), 0);
  assert.equal(stepWeek(2, 1, 3), 2);
  assert.equal(stepWeek(0, 1, 0), 0);
});

test("localToday: формат YYYY-MM-DD с нулями", () => {
  assert.equal(localToday(new Date(2026, 0, 5)), "2026-01-05");
});

test("groupCounter / weekProgress: перевыполнение не завышает прогресс", () => {
  assert.deepEqual(groupCounter([{ count_per_week: 3, done_count: 1 }, { count_per_week: 3, done_count: 1 }]),
    { done: 1, planned: 3 });
  const progress = weekProgress([
    [{ count_per_week: 2, done_count: 5 }],
    [{ count_per_week: 1, done_count: 0 }],
  ]);
  assert.deepEqual(progress, { done: 2, total: 3 });
  assert.deepEqual(weekProgress([]), { done: 0, total: 0 });
});

test("canAdvanceWeek: до MAX_FUTURE_WEEKS недель вперёд от текущей", () => {
  assert.equal(canAdvanceWeek(0, 1, 0), true);
  assert.equal(canAdvanceWeek(3, 4, 0), true);
  assert.equal(canAdvanceWeek(4, 5, 0), false);
  assert.equal(canAdvanceWeek(1, 3, 1), true);
  assert.equal(canAdvanceWeek(5, 6, 1), false);
});

test("isEditableWeek: прошлые недели только для чтения", () => {
  assert.equal(isEditableWeek(0, 1), false);
  assert.equal(isEditableWeek(1, 1), true);
  assert.equal(isEditableWeek(3, 1), true);
});

test("resolveCurrentWeekIndex/Id: current_week_id сервера важнее «последней недели»", () => {
  const weeks = [
    { id: 1, start_date: "2026-09-28" },
    { id: 2, start_date: "2026-10-05" },
    { id: 3, start_date: "2026-10-12" },
  ];
  // сервер: текущая — id 1 (часовой пояс пользователя); локальная дата устройства уже «в будущем»
  assert.equal(resolveCurrentWeekIndex(weeks, 1, "2026-10-06"), 0);
  assert.equal(resolveCurrentWeekId(weeks, 1, "2026-10-06"), 1);
  // будущие недели в конце списка текущими не считаются
  assert.equal(resolveCurrentWeekId(weeks, 2, "2026-10-06"), 2);
  // нет поля (старый ответ) или неизвестный id → фолбэк по локальной дате
  assert.equal(resolveCurrentWeekId(weeks, undefined, "2026-10-06"), 2);
  assert.equal(resolveCurrentWeekId(weeks, null, "2026-10-06"), 2);
  assert.equal(resolveCurrentWeekId(weeks, 99, "2026-10-06"), 2);
  assert.equal(resolveCurrentWeekId([], 5, "2026-10-06"), null);
});

test("progressPercent: доли, зажим, пустой план", async () => {
  const { progressPercent } = await import("../src/planWeekNav.ts");
  assert.equal(progressPercent(0, 6), 0);
  assert.equal(progressPercent(1, 3), 33);
  assert.equal(progressPercent(2, 3), 67);
  assert.equal(progressPercent(6, 6), 100);
  assert.equal(progressPercent(9, 6), 100);
  assert.equal(progressPercent(0, 0), 0);
  assert.equal(progressPercent(3, 0), 0);
  assert.equal(progressPercent(-1, 4), 0);
});

test("todayDayIndex: 0 = понедельник … 6 = воскресенье", async () => {
  const { todayDayIndex } = await import("../src/planWeekNav.ts");
  assert.equal(todayDayIndex(new Date(2026, 9, 5)), 0); // пн
  assert.equal(todayDayIndex(new Date(2026, 9, 2)), 4); // пт
  assert.equal(todayDayIndex(new Date(2026, 9, 4)), 6); // вс
});
