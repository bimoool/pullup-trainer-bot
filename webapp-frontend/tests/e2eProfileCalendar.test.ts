import assert from "node:assert/strict";
import { test } from "node:test";

import { performedOnForUtcAge } from "../e2e/fixtures/profileCalendar.ts";

for (const [now, performedAt, expectedLocalDay] of [
  ["2026-11-15T23:59:59Z", "2026-11-13T23:50:00Z", "2026-11-14"],
  ["2026-11-16T00:00:00Z", "2026-11-13T23:50:00Z", "2026-11-15"],
  ["2026-11-16T00:00:00Z", "2026-11-14T02:50:00+03:00", "2026-11-15"],
  ["2027-02-01T00:00:00Z", "2027-01-29T23:50:00Z", "2027-01-31"],
  ["2029-01-01T00:00:00Z", "2028-12-29T23:50:00Z", "2028-12-31"],
  ["2026-11-16T00:24:00Z", "2026-11-13T12:00:00Z", "2026-11-14"],
] as const) {
  test(`D2 dates-only preparation: ${now} / stored ${performedAt}`, () => {
    assert.equal(performedOnForUtcAge(performedAt, new Date(now), 2, "Europe/Moscow"), expectedLocalDay);
  });
}
