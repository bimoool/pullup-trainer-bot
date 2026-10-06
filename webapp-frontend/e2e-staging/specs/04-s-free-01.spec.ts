import { clickAndSync, confirmPreScreen, expect, nav, playSets, test } from "../fixtures/app";

/**
 * S-FREE-01 — a workout started without any plan row: the shipped system workout «Максимум подтягиваний»
 * (4 max attempts, migration a4c8e1f7b2d9) from Home -> detail -> Start -> complete -> Journal.
 */
test("S-FREE-01: start a system workout with no plan, complete, see it in Journal", async ({ qa }, testInfo) => {
  const s = await qa("qa_fresh_active");
  const { page } = s;
  await nav(page, "Главная").click();

  const section = page.getByTestId("system-workouts");
  await expect(section).toBeVisible();
  await section.getByRole("button", { name: /Максимум подтягиваний/ }).click();
  await expect(page.getByTestId("workout-detail-items")).toContainText("Подтягивания");
  await page.getByTestId("workout-detail-start").click();
  await confirmPreScreen(page);
  await expect(page.getByText(/Попытка 1\/4/)).toBeVisible();
  await playSets(page, ["20", "18", "17", "15"]);
  await page.getByRole("button", { name: "Завершить", exact: true }).first().click();
  await clickAndSync(page, "Сохранить и завершить", "/complete");
  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("s-free-01-summary.png") });
  await page.getByRole("button", { name: "Закрыть" }).click();

  await page.reload();
  await nav(page, "Журнал").click();
  await expect(page.locator(".history-card").filter({ hasText: /Максимум подтягиваний|Свободная/ }).first()).toBeVisible();
  await page.reload();
  await nav(page, "Журнал").click();
  await expect(page.locator(".history-card").filter({ hasText: /Максимум подтягиваний|Свободная/ }).first()).toBeVisible();

  s.assertClean();
});
