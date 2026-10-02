import assert from "node:assert/strict";
import { test } from "node:test";

import {
  completedInclusions, groupScheduleByPhase, inclusionDateRange, inclusionWeekLabel,
} from "../src/plansOverview.ts";

test("inclusionWeekLabel: только при заданной длине курса", () => {
  assert.equal(inclusionWeekLabel({ duration_weeks: 8, current_week: 3 }), "Неделя 3 из 8");
  assert.equal(inclusionWeekLabel({ duration_weeks: null, current_week: null }), null);
  assert.equal(inclusionWeekLabel({}), null);
});

test("inclusionDateRange: с датой окончания и без", () => {
  const range = inclusionDateRange({ started_at: "2026-09-01T12:00:00Z", expires_at: "2026-10-05T12:00:00Z" });
  assert.match(range, /^1 сен 2026 – 5 окт 2026$/);
  assert.match(inclusionDateRange({ started_at: "2026-09-01T12:00:00Z", expires_at: null }), /^с 1 сен 2026$/);
});

test("completedInclusions: только неактивные, недавно завершённые сверху", () => {
  const list = [
    { id: 1, is_active: false, started_at: "2026-08-01T00:00:00Z", expires_at: "2026-09-30T00:00:00Z" },
    { id: 2, is_active: true, started_at: "2026-08-01T00:00:00Z", expires_at: null },
    { id: 3, is_active: false, started_at: "2026-09-01T00:00:00Z", expires_at: "2026-09-10T00:00:00Z" },
    { id: 4, is_active: false, started_at: "2026-09-01T00:00:00Z", expires_at: "2026-10-01T00:00:00Z" },
  ];
  assert.deepEqual(completedInclusions(list).map((i) => i.id), [4, 1, 3]);
});

test("groupScheduleByPhase: порядок фаз сохраняется", () => {
  const items = [
    { week_phase: "base", day_of_week: 1 }, { week_phase: "peak", day_of_week: 0 }, { week_phase: "base", day_of_week: null },
  ];
  const groups = groupScheduleByPhase(items);
  assert.deepEqual(groups.map(([phase, rows]) => [phase, rows.length]), [["base", 2], ["peak", 1]]);
});
