import assert from "node:assert/strict";
import { test } from "node:test";

import { formatSessionDateTime, formatSessionTime } from "../src/journalTime.ts";

test("время карточки — в поясе журнала: 23:30 UTC в Europe/Moscow это 02:30 следующего дня", () => {
  assert.equal(formatSessionTime("2026-10-01T23:30:00Z", "Europe/Moscow"), "02:30");
  assert.equal(formatSessionDateTime("2026-10-01T23:30:00Z", "Europe/Moscow"), "02.10.2026, 02:30");
});

test("полночь отображается как 00:xx (24-часовой формат), другой пояс — другое время", () => {
  assert.equal(formatSessionTime("2026-10-01T21:05:00Z", "Europe/Moscow"), "00:05");
  assert.equal(formatSessionTime("2026-10-01T23:30:00Z", "Pacific/Kiritimati"), "13:30");
  assert.equal(formatSessionTime("2026-10-01T23:30:00Z", "UTC"), "23:30");
});
