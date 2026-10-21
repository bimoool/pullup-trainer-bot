import assert from "node:assert/strict";
import { test } from "node:test";

import { formatAvailableFrom, pickHomeTraining } from "../src/homeTraining.ts";
import { canStartOccurrence, occurrenceStateLabel, restBlockedUntil } from "../src/planWeekNav.ts";

const inclusion = (id: number, active = true) => ({ id, program_name: "Подтягивания", is_active: active });
const item = (id: number, occurrence: number, state: string, extra: Record<string, unknown> = {}) => ({
  id, plan_week_id: 65, program_inclusion_id: 13, occurrence_index: occurrence, status: "open", state,
  legacy_aggregate: false, credited_session_id: null, available_from: "2026-10-20", spacing_group: "main", ...extra,
});
const mainSpacing = (availableFrom: string | null) => [{ spacing_group: "main", min_days_between_starts: 3, last_start_date: null, available_from: availableFrom }];
const plan = (items: unknown[], opts: { inclusions?: unknown[]; current?: number | null; spacing?: unknown[]; today?: string } = {}) =>
  ({
    program_inclusions: opts.inclusions ?? [inclusion(13)], plan_items: items, current_week_id: opts.current === undefined ? 65 : opts.current,
    spacing: opts.spacing ?? mainSpacing(null), today: opts.today ?? "2026-10-21",
  }) as never;

test("берёт первое доступное занятие текущей недели (1 и 2 доступны, 3 не успеть)", () => {
  const result = pickHomeTraining(plan([item(320, 3, "infeasible"), item(319, 2, "available"), item(318, 1, "available")]), "2026-10-21");
  assert.deepEqual(result, { kind: "start", planItemIds: [318], title: "Подтягивания" });
});

test("занятия прошлых недель, засчитанные и legacy-агрегаты не стартуются", () => {
  const result = pickHomeTraining(plan([
    item(63, 1, "available", { plan_week_id: 13 }),
    item(64, 1, "available", { credited_session_id: 74 }),
    item(65, 2, "available", { legacy_aggregate: true }),
    item(66, 3, "available", { status: "removed" }),
  ]), "2026-10-21");
  assert.deepEqual(result, { kind: "none" });
});

test("слишком рано: вход не стартует, а сообщает дату", () => {
  assert.deepEqual(
    pickHomeTraining(plan([item(1, 1, "too_early", { available_from: "2026-10-22" })], { spacing: mainSpacing("2026-10-22") }), "2026-10-21"),
    { kind: "wait", availableFrom: "2026-10-22" },
  );
});

test("нет плана, нет текущей недели или курс неактивен — none", () => {
  assert.deepEqual(pickHomeTraining(null, "2026-10-21"), { kind: "none" });
  assert.deepEqual(pickHomeTraining(plan([item(1, 1, "available")], { current: null }), "2026-10-21"), { kind: "none" });
  assert.deepEqual(pickHomeTraining(plan([item(1, 1, "available")], { inclusions: [inclusion(13, false)] }), "2026-10-21"), { kind: "none" });
});

// Неделя 19–25 октября владельца: 1 засчитано, 2 «доступно с 23 окт», 3 «не успеть», сегодня 21 окт, отдых до 23.
const OWNER_WEEK = [
  item(495, 1, "completed", { credited_session_id: 78, available_from: null }),
  item(496, 2, "too_early", { available_from: "2026-10-23" }),
  item(497, 3, "infeasible", { available_from: "2026-10-23" }),
];

test("регрессия (неделя 19–25 окт): «не успеть» под действующим отдыхом не стартуется ни с Главной, ни с Планов", () => {
  const owner = plan(OWNER_WEEK, { spacing: mainSpacing("2026-10-23") });
  assert.deepEqual(pickHomeTraining(owner, "2026-10-21"), { kind: "wait", availableFrom: "2026-10-23" });
  const blocked = restBlockedUntil(OWNER_WEEK[2], mainSpacing("2026-10-23"), "2026-10-21");
  assert.equal(blocked, "2026-10-23");
  assert.equal(canStartOccurrence(OWNER_WEEK[2], blocked), false); // раньше: кнопка «Начать» активна
  assert.equal(canStartOccurrence(OWNER_WEEK[1], blocked), false);
  assert.equal(canStartOccurrence(OWNER_WEEK[0], blocked), false); // «Ещё раз» тоже под отдыхом
  assert.equal(occurrenceStateLabel(OWNER_WEEK[2], blocked), "Не успеть на этой неделе · старт с 23 окт");
  assert.equal(occurrenceStateLabel(OWNER_WEEK[1], blocked), "Доступно с 23 окт");
});

test("отдых закончился (23 окт): «не успеть» снова стартуется, Главная и Планы согласованы", () => {
  const spacing = mainSpacing("2026-10-23");
  assert.equal(restBlockedUntil(OWNER_WEEK[2], spacing, "2026-10-23"), null);
  assert.equal(canStartOccurrence({ state: "infeasible" }, null), true);
  const open = plan([item(496, 2, "available"), item(497, 3, "infeasible")], { spacing, today: "2026-10-23" });
  assert.deepEqual(pickHomeTraining(open, "2026-10-23"), { kind: "start", planItemIds: [496], title: "Подтягивания" });
  // Остался только «не успеть», отдыха нет — Планы дают «Начать», значит и Главная предлагает его.
  const only = plan([item(497, 3, "infeasible")], { spacing, today: "2026-10-23" });
  assert.deepEqual(pickHomeTraining(only, "2026-10-23"), { kind: "start", planItemIds: [497], title: "Подтягивания" });
});

test("группа без отдыха (свой план) и строки без spacing_group не блокируются", () => {
  assert.equal(restBlockedUntil({ spacing_group: null }, mainSpacing("2026-10-23"), "2026-10-21"), null);
  assert.equal(restBlockedUntil({ spacing_group: "main" }, undefined, "2026-10-21"), null);
});

test("formatAvailableFrom: календарная дата без сдвига часового пояса", () => {
  assert.equal(formatAvailableFrom("2026-10-22"), "22 окт");
  assert.equal(formatAvailableFrom("2026-01-05"), "5 янв");
  assert.equal(formatAvailableFrom(null), null);
  assert.equal(formatAvailableFrom("мусор"), null);
});
