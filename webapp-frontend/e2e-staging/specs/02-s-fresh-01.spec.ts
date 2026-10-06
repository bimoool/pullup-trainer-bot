import { confirmPreScreen, expect, finishAndSave, nav, playSets, test } from "../fixtures/app";

/**
 * S-FRESH-01 — qa_fresh_active (onboarded, active subscription, NO plan, NO history; reset by provisioning).
 * Pure UI: Home -> «Подтягивания» -> add -> Plans -> actionable workout -> Start -> Live -> log sets ->
 * Complete -> Journal -> Analytics -> reload. No PlanItem is created outside the product.
 */
test("S-FRESH-01: fresh user — course to journal and analytics, survives reload", async ({ qa }, testInfo) => {
  const s = await qa("qa_fresh_active");
  const { page } = s;

  // Precondition: the identity really is fresh (otherwise this journey proves nothing).
  await nav(page, "Планы").click();
  await expect(page.getByTestId("plans-now-empty"), "qa_fresh_active is not fresh — reprovision it (docs/STAGING_QA_HARNESS.md)").toBeVisible();
  await nav(page, "Главная").click();

  await expect(page.getByTestId("program-row").first()).toBeVisible();
  await page.getByRole("button", { name: /^Подтягивания/ }).first().click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await expect(page.getByRole("button", { name: "В плане", exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("s-fresh-01-added.png") });

  await page.getByRole("button", { name: /Назад/ }).first().click();
  await nav(page, "Планы").click();
  await expect(page.getByTestId("plan-week-progress").first()).not.toHaveText(/0 из 0/);
  const start = page.getByRole("button", { name: /^Начать: Подтягивания/ }).first();
  await expect(start).toBeVisible();

  await page.reload();
  await nav(page, "Планы").click();
  await expect(page.getByRole("button", { name: /^Начать: Подтягивания/ }).first()).toBeVisible();

  await page.getByRole("button", { name: /^Начать: Подтягивания/ }).first().click();
  await confirmPreScreen(page);
  await playSets(page, ["10", "10", "10"]);
  await finishAndSave(page);
  await page.screenshot({ path: testInfo.outputPath("s-fresh-01-summary.png") });
  await page.getByRole("button", { name: "Закрыть" }).click();

  await page.reload();
  await nav(page, "Журнал").click();
  await expect(page.locator(".history-card").filter({ hasText: "Подтягивания" }).first()).toBeVisible();
  await page.reload();
  await nav(page, "Журнал").click();
  await expect(page.locator(".history-card").filter({ hasText: "Подтягивания" }).first()).toBeVisible();

  await nav(page, "Аналитика").click();
  const stat = page.locator(".analytics-activity-cards .analytics-stat").filter({ hasText: "Тренировок за 30 дней" });
  await expect(stat).toContainText("1");
  await page.screenshot({ path: testInfo.outputPath("s-fresh-01-analytics.png") });

  await page.reload();
  await nav(page, "Планы").click();
  await expect(page.getByTestId("plan-week-progress").first()).toHaveText(/Текущая неделя · [1-9]\d* из \d+/);

  s.assertClean();
});
