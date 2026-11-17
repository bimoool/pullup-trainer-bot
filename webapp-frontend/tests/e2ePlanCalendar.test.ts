import assert from "node:assert/strict";
import { test } from "node:test";

import { currentPlanWeek, planWeekLabel, relativePlanWeekNumber } from "../e2e/fixtures/planCalendar.ts";

for (const [createdAt, today, monday, number] of [
  ["2026-11-15T20:59:59Z", "2026-11-15", "2026-11-09", 1],
  ["2026-11-15T21:00:00Z", "2026-11-16", "2026-11-16", 2],
  ["2026-11-16T00:00:00+03:00", "2026-11-16", "2026-11-16", 2],
  ["2026-11-15T23:59:59Z", "2026-11-16", "2026-11-16", 2],
  ["2026-11-16T00:00:00Z", "2026-11-16", "2026-11-16", 1],
  ["2027-01-31T21:00:00Z", "2027-02-01", "2027-02-01", 2],
  ["2028-12-31T21:00:00Z", "2029-01-01", "2029-01-01", 2],
] as const) {
  test(`E2E week contract: ${createdAt} / local ${today}`, () => {
    const current = { id: 72, week_number: number, start_date: monday, phase: "base" };
    const plan = { created_at: createdAt, today, current_week_id: current.id, plan_weeks: [current] };
    assert.deepEqual(currentPlanWeek(plan), current);
    assert.equal(planWeekLabel(current), `Неделя ${number} · ${
      monday === "2026-11-09" ? "9 ноя – 15 ноя"
        : monday === "2026-11-16" ? "16 ноя – 22 ноя"
          : monday === "2027-02-01" ? "1 фев – 7 фев" : "1 янв – 7 янв"
    }`);
    assert.equal(relativePlanWeekNumber(current, 1), number + 1);
    assert.equal(relativePlanWeekNumber(current, 2), number + 2);
  });
}

test("current_week_id wins over array order and future weeks; inconsistent API dates fail", () => {
  const current = { id: 72, week_number: 2, start_date: "2026-11-16", phase: "base" };
  const plan = {
    created_at: "2026-11-15T21:00:00Z", today: "2026-11-16", current_week_id: current.id,
    plan_weeks: [{ ...current, id: 90, week_number: 3, start_date: "2026-11-23" }, current],
  };
  assert.deepEqual(currentPlanWeek(plan), current);
  assert.throws(() => currentPlanWeek({ ...plan, current_week_id: 999 }));
  assert.throws(() => currentPlanWeek({ ...plan, plan_weeks: [{ ...current, week_number: 1 }] }));
  assert.throws(() => currentPlanWeek({ ...plan, plan_weeks: [{ ...current, start_date: "2026-11-09" }] }));
});
