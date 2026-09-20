import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py plan_week_ready 900013 — RECURRING-курс с одним
// PlanItem по вторникам (day_of_week=1) и одним в свободном пуле
// (day_of_week=NULL), см. докстринг сценария. НЕ admin-only (в отличие от
// v2_session_* сценариев волны 5) — вкладка "Планы" видна всем.
const TELEGRAM_ID = 900_013;

// issue #193 (WORKER B) — критерий готовности из issue дословно: "«Планы»
// → видна текущая «Неделя N» → элементы реально относятся к этой PlanWeek
// (проверь через API-ответ, не только визуально)". Ловим сам ответ GET
// /api/v2/plan и сверяем plan_week_id каждого plan_item с id материализованной
// недели — не полагаемся только на то, что показалось на экране.
test("«Планы»: видна текущая неделя плана, элементы реально относятся к ней", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);

  const planResponsePromise = page.waitForResponse(
    (response) => response.url().includes("/api/v2/plan") && response.status() === 200,
  );

  await page.getByRole("button", { name: "Планы" }).click();

  const planResponse = await planResponsePromise;
  const plan = (await planResponse.json()).plan as {
    plan_weeks: { id: number; week_number: number; phase: string }[];
    plan_items: { id: number; day_of_week: number | null; plan_week_id: number | null }[];
  };

  expect(plan.plan_weeks).toHaveLength(1);
  const week = plan.plan_weeks[0];
  expect(week.week_number).toBe(1);
  expect(week.phase).toBe("base");

  expect(plan.plan_items).toHaveLength(2);
  for (const item of plan.plan_items) {
    expect(item.plan_week_id).toBe(week.id);
  }
  expect(plan.plan_items.filter((item) => item.day_of_week !== null)).toHaveLength(1);
  expect(plan.plan_items.filter((item) => item.day_of_week === null)).toHaveLength(1);

  // Визуально — текущая неделя подписана явно ("текущая"), элементы видны и
  // разделены на "по дням"/"свободный пул" (не смешаны в один список).
  await expect(page.getByText("Неделя 1 · текущая · База")).toBeVisible();
  await expect(page.getByText("Вторник")).toBeVisible();
  await expect(page.getByText("По вторникам · 1×/нед")).toBeVisible();
  await expect(page.getByText("Свободный пул")).toBeVisible();
  await expect(page.getByText("Свободная тренировка · 3×/нед")).toBeVisible();

  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});
