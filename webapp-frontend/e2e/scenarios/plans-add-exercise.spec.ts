import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py plan_week_add_exercise 900015 — активная RECURRING-
// инклюзия «Подтягивания» (2 блока, свободный пул) + засеянная Exercise
// Library (Планка/Отжимания). НЕ admin-only — вкладка «Планы» видна всем.
const TELEGRAM_ID = 900_015;

test("«Планы»: добавить Планку в Среду и Отжимания в Пятницу через picker", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);

  await page.getByRole("button", { name: "Планы" }).click();
  await expect(page.getByText("Свободный пул")).toBeVisible();
  await expect(page.getByText("Подтягивания")).toBeVisible();

  // --- Добавить "Планка" в Среду ---
  await page.getByRole("button", { name: "+ Добавить упражнение" }).click();
  await expect(page.getByText("Добавить упражнение")).toBeVisible();
  await page.getByRole("button", { name: "Планка", exact: true }).click();
  await page.getByRole("button", { name: "Среда", exact: true }).click();

  const planResponsePromise1 = page.waitForResponse(
    (response) => response.url().includes("/api/v2/plan") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  await planResponsePromise1;
  await page.waitForTimeout(500);

  // picker закрылся после успешного добавления
  await expect(page.getByText("Добавить упражнение")).toHaveCount(0);
  await expect(page.getByText("Среда")).toBeVisible();
  await expect(page.getByText("Планка", { exact: true })).toBeVisible();

  // --- Добавить "Отжимания" в Пятницу ---
  await page.getByRole("button", { name: "+ Добавить упражнение" }).click();
  await page.getByRole("button", { name: "Отжимания", exact: true }).click();
  await page.getByRole("button", { name: "Пятница", exact: true }).click();

  const planResponsePromise2 = page.waitForResponse(
    (response) => response.url().includes("/api/v2/plan") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  await planResponsePromise2;
  await page.waitForTimeout(500);

  await expect(page.getByText("Пятница")).toBeVisible();
  await expect(page.getByText("Отжимания", { exact: true })).toBeVisible();

  // --- Manual-семантика: имена реальные, не "Упражнение #id", не слиплись ---
  await expect(page.getByText(/^Упражнение #/)).toHaveCount(0);
  await expect(page.getByText("Планка", { exact: true })).toHaveCount(1);
  await expect(page.getByText("Отжимания", { exact: true })).toHaveCount(1);

  // --- Grouping regression (Checkpoint 2): Block A/Б не появились отдельно ---
  await expect(page.getByText("Блок A", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Блок Б", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Подтягивания", { exact: true })).toHaveCount(1);

  expect(apiFailures).toEqual([]);
  expect(consoleErrors).toEqual([]);

  // --- Reload proof ---
  const planReloadPromise = page.waitForResponse(
    (response) => response.url().includes("/api/v2/plan") && response.status() === 200,
  );
  await page.reload({ waitUntil: "networkidle" });
  const planReload = await planReloadPromise;
  const planData = (await planReload.json()).plan as {
    plan_items: {
      exercise_id: number; program_inclusion_id: number | null; plan_week_id: number | null;
      day_of_week: number | null;
    }[];
  };

  await page.getByRole("button", { name: "Планы" }).click();
  await expect(page.getByText("Свободный пул")).toBeVisible();
  await expect(page.getByText("Подтягивания", { exact: true })).toHaveCount(1);
  await expect(page.getByText("Среда")).toBeVisible();
  await expect(page.getByText("Планка", { exact: true })).toBeVisible();
  await expect(page.getByText("Пятница")).toBeVisible();
  await expect(page.getByText("Отжимания", { exact: true })).toBeVisible();
  await expect(page.getByText("Блок A", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Блок Б", { exact: true })).toHaveCount(0);
  await expect(page.getByText(/^Упражнение #/)).toHaveCount(0);

  // Backend-proof точных значений, не только видимого текста.
  const manualItems = planData.plan_items.filter((item) => item.program_inclusion_id === null);
  expect(manualItems).toHaveLength(2);
  const wednesdayItem = manualItems.find((item) => item.day_of_week === 2); // 0=Пн..2=Ср
  const fridayItem = manualItems.find((item) => item.day_of_week === 4); // 4=Пт
  expect(wednesdayItem).toBeDefined();
  expect(fridayItem).toBeDefined();
  expect(wednesdayItem?.plan_week_id).not.toBeNull();
  expect(fridayItem?.plan_week_id).not.toBeNull();
  expect(wednesdayItem?.plan_week_id).toBe(fridayItem?.plan_week_id);
});
