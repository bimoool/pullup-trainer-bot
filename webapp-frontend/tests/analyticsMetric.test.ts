import assert from "node:assert/strict";
import { test } from "node:test";

import {
  formatMinutes, formatWeekLabel, localIsoDate, presetRange, shiftIsoDate, validateCustomRange,
} from "../src/analyticsMetric.ts";

test("shiftIsoDate: через границу месяца и года, високосный год", () => {
  assert.equal(shiftIsoDate("2026-03-01", -1), "2026-02-28");
  assert.equal(shiftIsoDate("2024-03-01", -1), "2024-02-29");
  assert.equal(shiftIsoDate("2026-01-01", -1), "2025-12-31");
  assert.equal(shiftIsoDate("2026-12-31", 1), "2027-01-01");
});

test("presetRange: 1 мес = 30 дней, 3 мес = 90 дней включая сегодня", () => {
  assert.deepEqual(presetRange("1m", "2026-10-01"), { from: "2026-09-02", to: "2026-10-01" });
  assert.deepEqual(presetRange("3m", "2026-10-01"), { from: "2026-07-04", to: "2026-10-01" });
});

test("localIsoDate: дата берётся в поясе пользователя, а не в UTC", () => {
  const instant = new Date("2026-03-01T21:30:00Z");
  assert.equal(localIsoDate(instant, "UTC"), "2026-03-01");
  assert.equal(localIsoDate(instant, "Europe/Moscow"), "2026-03-02");
});

test("validateCustomRange: пустые, перевёрнутые и слишком длинные диапазоны", () => {
  assert.equal(validateCustomRange("", "2026-03-01"), "Укажите обе даты");
  assert.equal(validateCustomRange("2026-03-02", "2026-03-01"), "Начало позже конца");
  assert.equal(validateCustomRange("2025-01-01", "2026-03-01"), "Не больше года");
  assert.equal(validateCustomRange("2026-03-01", "2026-03-01"), null);
  assert.equal(validateCustomRange("2025-03-01", "2026-03-01"), null); // 365 дней
});

test("formatWeekLabel и formatMinutes", () => {
  assert.equal(formatWeekLabel("2026-09-28"), "28.09");
  assert.equal(formatMinutes(0), "0 мин");
  assert.equal(formatMinutes(45), "45 мин");
  assert.equal(formatMinutes(120), "2 ч");
  assert.equal(formatMinutes(135), "2 ч 15 мин");
});
