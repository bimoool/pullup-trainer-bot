import assert from "node:assert/strict";
import { test } from "node:test";

import { pickHomeTraining } from "../src/homeTraining.ts";

const inclusion = (id: number, active = true) => ({ id, program_name: "Подтягивания", is_active: active });
const item = (id: number, occurrence: number, state: string, extra: Record<string, unknown> = {}) => ({
  id, plan_week_id: 65, program_inclusion_id: 13, occurrence_index: occurrence, status: "open", state,
  legacy_aggregate: false, credited_session_id: null, available_from: "2026-10-20", ...extra,
});
const plan = (items: unknown[], inclusions: unknown[] = [inclusion(13)], current: number | null = 65) =>
  ({ program_inclusions: inclusions, plan_items: items, current_week_id: current }) as never;

test("берёт первое доступное занятие текущей недели (реальный план владельца: 1 и 2 доступны, 3 не успеть)", () => {
  const result = pickHomeTraining(plan([item(320, 3, "infeasible"), item(319, 2, "available"), item(318, 1, "available")]));
  assert.deepEqual(result, { kind: "start", planItemIds: [318], title: "Подтягивания" });
});

test("занятия прошлых недель, засчитанные и legacy-агрегаты не стартуются", () => {
  const result = pickHomeTraining(plan([
    item(63, 1, "available", { plan_week_id: 13 }),
    item(64, 1, "available", { credited_session_id: 74 }),
    item(65, 2, "available", { legacy_aggregate: true }),
    item(66, 3, "available", { status: "removed" }),
  ]));
  assert.deepEqual(result, { kind: "none" });
});

test("слишком рано: вход не стартует, а сообщает дату", () => {
  assert.deepEqual(pickHomeTraining(plan([item(1, 1, "too_early", { available_from: "2026-10-22" })])), { kind: "wait", availableFrom: "2026-10-22" });
});

test("нет плана, нет текущей недели или курс неактивен — none", () => {
  assert.deepEqual(pickHomeTraining(null), { kind: "none" });
  assert.deepEqual(pickHomeTraining(plan([item(1, 1, "available")], [inclusion(13)], null)), { kind: "none" });
  assert.deepEqual(pickHomeTraining(plan([item(1, 1, "available")], [inclusion(13, false)])), { kind: "none" });
});
