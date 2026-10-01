import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildMonthGrid, currentMonthIn, dayLabel, groupByWeekAndDay, localDateKey, monthLabel, monthRange,
  shiftMonth, weekLabel, weekStartOf,
} from "../src/journalCalendar.ts";

test("shiftMonth: через границу года в обе стороны", () => {
  assert.equal(shiftMonth("2026-12", 1), "2027-01");
  assert.equal(shiftMonth("2026-01", -1), "2025-12");
  assert.equal(shiftMonth("2026-10", 0), "2026-10");
  assert.equal(shiftMonth("2026-10", -13), "2025-09");
});

test("monthLabel / monthRange", () => {
  assert.equal(monthLabel("2026-10"), "Октябрь 2026");
  assert.deepEqual(monthRange("2026-02"), { from: "2026-02-01", to: "2026-02-28" });
  assert.deepEqual(monthRange("2028-02"), { from: "2028-02-01", to: "2028-02-29" });
  assert.deepEqual(monthRange("2026-10"), { from: "2026-10-01", to: "2026-10-31" });
});

test("localDateKey: день считается в поясе пользователя, не браузера", () => {
  assert.equal(localDateKey("2026-09-30T21:30:00Z", "Europe/Moscow"), "2026-10-01");
  assert.equal(localDateKey("2026-09-30T21:30:00Z", "UTC"), "2026-09-30");
  assert.equal(localDateKey("2026-10-02T02:00:00Z", "America/New_York"), "2026-10-01");
  assert.equal(currentMonthIn("Europe/Moscow", new Date("2026-10-31T21:30:00Z")), "2026-11");
});

test("buildMonthGrid: Пн-первая, 7 ячеек в неделе, пустые — null", () => {
  const grid = buildMonthGrid("2026-10"); // 1 октября 2026 — четверг
  assert.ok(grid.every((week) => week.length === 7));
  assert.deepEqual(grid[0].slice(0, 4), [null, null, null, "2026-10-01"]);
  assert.equal(grid[grid.length - 1].find((cell) => cell !== null && cell.endsWith("-31")), "2026-10-31");
  assert.equal(grid.flat().filter((cell) => cell !== null).length, 31);
  // месяц, начинающийся с понедельника, без ведущих пустых ячеек
  assert.equal(buildMonthGrid("2026-06")[0][0], "2026-06-01");
});

test("weekStartOf / weekLabel / dayLabel", () => {
  assert.equal(weekStartOf("2026-10-01"), "2026-09-28");
  assert.equal(weekStartOf("2026-10-04"), "2026-09-28"); // воскресенье
  assert.equal(weekStartOf("2026-10-05"), "2026-10-05");
  assert.equal(weekLabel("2026-09-28"), "28 сен. – 4 окт.");
  assert.equal(weekLabel("2026-10-05"), "5–11 окт.");
  assert.equal(dayLabel("2026-10-01"), "Чт, 1 октября");
});

test("groupByWeekAndDay: новые недели и дни первыми, порядок внутри дня сохранён", () => {
  const weeks = groupByWeekAndDay([
    { date: "2026-10-06", item: "a" },
    { date: "2026-10-06", item: "b" },
    { date: "2026-10-01", item: "c" },
    { date: "2026-10-03", item: "d" },
  ]);
  assert.deepEqual(weeks.map((week) => week.weekStart), ["2026-10-05", "2026-09-28"]);
  assert.deepEqual(weeks[0].days, [{ date: "2026-10-06", items: ["a", "b"] }]);
  assert.deepEqual(weeks[1].days.map((day) => day.date), ["2026-10-03", "2026-10-01"]);
  assert.deepEqual(groupByWeekAndDay([]), []);
});
