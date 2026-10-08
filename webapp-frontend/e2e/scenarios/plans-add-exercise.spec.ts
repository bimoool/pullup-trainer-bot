import { expect, test, type Page } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py plan_week_add_exercise 900015 — активная RECURRING-
// инклюзия «Подтягивания» (2 блока, свободный пул) + засеянная Exercise
// Library (Планка/Отжимания). НЕ admin-only — вкладка «Планы» видна всем.
const TELEGRAM_ID = 900_015;
// #286 B: строка недели = название и чип «сделано/план» отдельными элементами (раньше «Название · 0/1» одним текстом).
// Блок «Сегодня» повторяет сегодняшние названия — ищем только в недельном списке (plans-row).
const rowTitle = (page: Page, name: string) =>
  page.getByTestId("plans-row").locator(".plans-row-title").filter({ hasText: new RegExp(`^${name}$`) });
const rowCounter = (page: Page, name: string) => page.getByTestId("plans-row")
  .filter({ has: page.locator(".plans-row-title").filter({ hasText: new RegExp(`^${name}$`) }) })
  .getByTestId("plan-item-counter");

test("«Планы»: добавить Планку в Среду и Отжимания в Пятницу через picker", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);

  await page.getByRole("button", { name: "Планы" }).click();
  await expect(page.getByText("Свободный пул")).toBeVisible();
  // #266: имя курса есть и в карточке плана, и в строке недели — проверяем строку недели.
  // #304: «Подтягивания» × 3 — три строки-занятия, у каждой «0/1».
  await expect(rowTitle(page, "Подтягивания").first()).toBeVisible();
  await expect(rowCounter(page, "Подтягивания").first()).toHaveText(/^\d+\/\d+$/);

  // --- Добавить "Планка" в Среду ---
  await page.getByRole("button", { name: "+ Добавить упражнение" }).click();
  await expect(page.getByRole("heading", { name: "Добавить упражнение" })).toBeVisible();
  await page.getByRole("button", { name: "Планка", exact: true }).click();
  await page.getByRole("button", { name: "Среда", exact: true }).click();

  const planResponsePromise1 = page.waitForResponse(
    (response) => response.url().includes("/api/v2/plan") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  await planResponsePromise1;

  // picker закрылся после успешного добавления
  await expect(page.getByRole("heading", { name: "Добавить упражнение" })).toHaveCount(0);
  await expect(page.getByText("Среда")).toBeVisible();
  await expect(rowTitle(page, "Планка")).toBeVisible();

  // --- Добавить "Отжимания" в Пятницу ---
  await page.getByRole("button", { name: "+ Добавить упражнение" }).click();
  await page.getByRole("button", { name: "Отжимания", exact: true }).click();
  await page.getByRole("button", { name: "Пятница", exact: true }).click();

  const planResponsePromise2 = page.waitForResponse(
    (response) => response.url().includes("/api/v2/plan") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  await planResponsePromise2;

  await expect(page.getByText("Пятница")).toBeVisible();
  await expect(rowTitle(page, "Отжимания")).toBeVisible();

  // --- Manual-семантика: имена реальные, не "Упражнение #id", не слиплись ---
  await expect(page.getByText(/^Упражнение #/)).toHaveCount(0);
  await expect(rowTitle(page, "Планка")).toHaveCount(1);
  await expect(rowTitle(page, "Отжимания")).toHaveCount(1);

  // --- Grouping regression (Checkpoint 2): Block A/Б не появились отдельно ---
  await expect(page.getByText("Блок A", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Блок Б", { exact: true })).toHaveCount(0);
  // issue #258 — к названию группы теперь добавлен счётчик «сделано/план».
  await expect(rowTitle(page, "Подтягивания")).toHaveCount(3);  // #304: три занятия-строки курса

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
  // issue #258 — к названию группы теперь добавлен счётчик «сделано/план».
  await expect(rowTitle(page, "Подтягивания")).toHaveCount(1);
  await expect(page.getByText("Среда")).toBeVisible();
  await expect(rowTitle(page, "Планка")).toBeVisible();
  await expect(page.getByText("Пятница")).toBeVisible();
  await expect(rowTitle(page, "Отжимания")).toBeVisible();
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
