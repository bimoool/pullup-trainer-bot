import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// Регрессия: с Главной (каталог) не было входа в тренировку — только баннер «план дня» внизу,
// ведущий на «Планы». Теперь на Главной есть «Начать тренировку» → предстарт → живая тренировка.
// scripts/e2e_seed.py plan_week_start_session 930801 (курс V5.6, свежая инклюзия).
const TELEGRAM_ID = 930_801;

test("Главная → «Начать тренировку» → предстарт → живая тренировка", async ({ page }) => {
  const { apiFailures } = await openAppAs(page, TELEGRAM_ID);

  await expect(page.locator(".plan-title")).toHaveText("Главная");
  await page.getByTestId("home-training-start").click(); // без захода на «Планы»
  await page.getByRole("button", { name: "Начать", exact: true }).click(); // SessionPreScreen
  await expect(page.getByText("Живая тренировка")).toBeVisible();
  expect(apiFailures).toEqual([]);
});
