import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py journal_combined 900018 — один пользователь: legacy
// Workout запись (10 дней назад) + реальная STEP-программа "Подтягивания"
// + manual "Планка"/"Отжимания" по дням, готовые к Start. Ни одна v2-сессия
// ещё не начата — Golden Journey проходит их вживую. НЕ admin-only.
const TELEGRAM_ID = 900_018;

test("Планы → Подтягивания/Планка → Complete → Журнал показывает обе + legacy не пропала", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);

  async function logSet(value: string) {
    if (await page.getByRole("button", { name: "Пропустить отдых", exact: true }).count() > 0) {
      await page.getByRole("button", { name: "Пропустить отдых", exact: true }).click();
    }
    if (await page.getByRole("button", { name: "Готов", exact: true }).count() > 0) {
      await page.getByRole("button", { name: "Готов", exact: true }).click();
      await page.waitForSelector("text=Пошёл", { timeout: 8000 });
    }
    await page.getByLabel("Результат").fill(value);
    const setResponsePromise = page.waitForResponse(
      (response) => response.url().includes("sets:batch") && response.status() === 200,
    );
    await page.getByRole("button", { name: "Готово", exact: true }).click();
    await setResponsePromise;
  }

  await page.getByRole("button", { name: "Планы" }).click();

  // --- Подтягивания: оба блока в одной Session ---
  await page.locator(".plan-week-day-group", { hasText: "Подтягивания" })
    .getByRole("button", { name: "Начать", exact: true }).click();
  const pullupsStartPromise = page.waitForResponse(
    (response) => response.url().includes("/api/v2/sessions/live") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  const pullupsStarted = await pullupsStartPromise.then((r) => r.json());
  expect(pullupsStarted.blocks).toHaveLength(2);

  await logSet("10");
  await logSet("9");
  await logSet("11");
  await logSet("3");
  const pullupsCompletePromise = page.waitForResponse(
    (response) => response.url().includes("/complete") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Завершить", exact: true }).click();
  await pullupsCompletePromise;
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();

  // --- Планка ---
  await page.getByRole("button", { name: "Планы" }).click();
  await page.locator(".plan-week-day-group", { hasText: "Планка" })
    .getByRole("button", { name: "Начать", exact: true }).click();
  await expect(page.getByText("Планка")).toBeVisible();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await logSet("30");
  const plankCompletePromise = page.waitForResponse(
    (response) => response.url().includes("/complete") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Завершить", exact: true }).click();
  await plankCompletePromise;
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();

  // --- Журнал: обе новые + legacy не пропала ---
  const journalResponsePromise = page.waitForResponse(
    (response) => response.url().includes("status=completed") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Журнал" }).click();
  const journal = await journalResponsePromise.then((r) => r.json());

  const titles = journal.sessions.map((s: { title: string | null }) => s.title);
  expect(titles).toContain("Подтягивания");
  expect(titles).toContain("Планка");

  await expect(page.getByText("Подтягивания", { exact: true })).toBeVisible();
  await expect(page.getByText("Планка", { exact: true })).toBeVisible();
  await expect(page.getByText("Блок A", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Блок Б", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Объём", { exact: false })).toBeVisible(); // legacy запись не пропала

  // --- Reload: всё то же самое из backend ---
  await page.reload({ waitUntil: "networkidle" });
  const reloadJournalPromise = page.waitForResponse(
    (response) => response.url().includes("status=completed") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Журнал" }).click();
  await reloadJournalPromise;
  await expect(page.getByText("Подтягивания", { exact: true })).toBeVisible();
  await expect(page.getByText("Планка", { exact: true })).toBeVisible();
  await expect(page.getByText("Объём", { exact: false })).toBeVisible();

  expect(apiFailures).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
