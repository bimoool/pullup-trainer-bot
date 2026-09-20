import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py plan_week_grouping 900014 — прямой воспроизводящий
// сценарий бага Worker B (issue #188, checkpoint 2 review): RECURRING-курс
// с двумя PlanItem (Блок A / Блок Б), одна ProgramInclusion, оба
// day_of_week=NULL — ровно форма реального сида "Подтягивания". Плюс один
// ручной PlanItem (program_inclusion_id=NULL) для проверки, что он не
// слипается с группой.
const TELEGRAM_ID = 900_014;

test("«Планы»: два PlanItem одной инклюзии с одинаковым day_of_week — ОДНА карточка, не две", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);

  const planResponsePromise = page.waitForResponse(
    (response) => response.url().includes("/api/v2/plan") && response.status() === 200,
  );

  await page.getByRole("button", { name: "Планы" }).click();

  const planResponse = await planResponsePromise;
  const plan = (await planResponse.json()).plan as {
    plan_items: { id: number; program_inclusion_id: number | null; day_of_week: number | null }[];
  };

  // Данные — три строки на входе: 2 от инклюзии (одинаковый day_of_week),
  // 1 ручная. Сам факт трёх строк в API не значит трёх карточек в UI —
  // именно это и проверяем ниже.
  expect(plan.plan_items).toHaveLength(3);
  const grouped = plan.plan_items.filter((item) => item.program_inclusion_id !== null);
  expect(grouped).toHaveLength(2);
  expect(new Set(grouped.map((item) => item.day_of_week))).toEqual(new Set([null]));

  // Главная проверка — ровно ОДНА карточка "Подтягивания (E2E group)" в
  // свободном пуле, не "Блок A" и "Блок Б" отдельными строками.
  await expect(page.getByText("Свободный пул")).toBeVisible();
  await expect(page.getByText("Подтягивания (E2E group)")).toHaveCount(1);
  await expect(page.getByText("Блок A", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Блок Б", { exact: true })).toHaveCount(0);

  // Ручной PlanItem — своя отдельная карточка, не слился ни с группой, ни
  // потерялся.
  await expect(page.getByText("Растяжка")).toBeVisible();

  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);

  // Сохраняется после перезагрузки страницы (не только на первом рендере
  // из кэша навигации).
  await page.reload();
  await page.getByRole("button", { name: "Планы" }).click();
  await expect(page.getByText("Подтягивания (E2E group)")).toHaveCount(1);
  await expect(page.getByText("Растяжка")).toBeVisible();
});
