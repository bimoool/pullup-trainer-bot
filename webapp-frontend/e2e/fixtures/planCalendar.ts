import assert from "node:assert/strict";

export interface CalendarWeek {
  id: number;
  week_number: number;
  start_date: string;
  phase: string;
}

export interface CalendarPlan {
  created_at: string;
  today: string;
  current_week_id: number;
  plan_weeks: CalendarWeek[];
}

const DAY_MS = 86_400_000;
const MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
const dateMs = (iso: string) => Date.parse(`${iso}T00:00:00Z`);
const mondayMs = (iso: string) => {
  const ms = dateMs(iso);
  return ms - ((new Date(ms).getUTCDay() + 6) % 7) * DAY_MS;
};

/** Independent E2E contract: use the explicit server id, then verify calendar arithmetic.
 * Plan creation is a stored UTC date; today is the API's user-local date.
 * Never infer the current week from array order or a literal "week 1". */
export function currentPlanWeek(plan: CalendarPlan): CalendarWeek {
  const matches = plan.plan_weeks.filter((week) => week.id === plan.current_week_id);
  assert.equal(matches.length, 1, "current_week_id must identify exactly one PlanWeek");
  const week = matches[0];
  assert.equal(dateMs(week.start_date), mondayMs(plan.today), "current week must start on local Monday");
  const createdUtcDate = new Date(plan.created_at).toISOString().slice(0, 10);
  const expectedNumber = 1 + (mondayMs(plan.today) - mondayMs(createdUtcDate)) / (7 * DAY_MS);
  assert.equal(week.week_number, expectedNumber, "PlanWeek number must agree with the plan's UTC creation date");
  return week;
}

export function relativePlanWeekNumber(current: CalendarWeek, offset: number): number {
  assert.ok(Number.isInteger(offset) && offset >= 0);
  return current.week_number + offset;
}

/** Full render oracle, deliberately independent of production planWeekNav.ts. */
export function planWeekLabel(week: CalendarWeek): string {
  const short = (ms: number) => {
    const date = new Date(ms);
    return `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]}`;
  };
  const start = dateMs(week.start_date);
  return `Неделя ${week.week_number} · ${short(start)} – ${short(start + 6 * DAY_MS)}`;
}
