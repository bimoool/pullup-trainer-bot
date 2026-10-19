import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// UX-28: удаление недели и тренировки — только через лист-подтверждение с названием потерь; «Отмена» ничего
// не меняет; после подтверждения последующие недели сдвигаются. Сид: ux_editor_fresh 941004.
const TELEGRAM_ID = 941_004;

test("UX-28: удаление недели и тренировки с подтверждением", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);
  await page.getByRole("button", { name: "Планы" }).click();
  await page.getByTestId("plans-custom-plan").click();
  await page.getByText("Тяга UX-А").click();
  await page.getByText("Тяга UX-Б").click();
  await page.getByTestId("plan-create-next").click();
  await page.getByTestId("plan-create-save").click();
  await expect(page.getByTestId("plan-editor-screen")).toBeVisible();
  for (const week of [1, 2, 3, 4]) {
    await expect(page.getByTestId(`editor-total-${week}`)).toHaveText("Всего 2");
  }

  // Неделя 3: подтверждение называет, что будет убрано; Отмена не меняет ничего
  await page.getByTestId("editor-delete-3").click();
  await expect(page.getByTestId("editor-confirm")).toContainText("Удалить неделю 3?");
  await expect(page.getByTestId("editor-confirm")).toContainText("Будет убрано занятий: 2");
  await page.getByTestId("editor-confirm-cancel").click();
  await expect(page.getByTestId("editor-week-4")).toBeVisible();

  await page.getByTestId("editor-delete-3").click();
  await page.getByTestId("editor-confirm-ok").click();
  await expect(page.getByTestId("editor-week-4")).toHaveCount(0);
  await expect(page.getByTestId("editor-week-3")).toBeVisible();

  // Вставка недели после недели 2: снова 4 недели, новая неделя 3 пустая («Неделя отдыха по плану»)
  await page.getByTestId("editor-insert-2").click();
  await expect(page.getByTestId("editor-week-4")).toBeVisible();
  await expect(page.getByTestId("editor-total-3")).toHaveText("Всего 0");
  await expect(page.getByTestId("editor-rest-note-3")).toHaveText("Неделя отдыха по плану");
  await expect(page.getByTestId("editor-total-4")).toHaveText("Всего 2");

  // Убрать тренировку: тоже с подтверждением
  await page.locator('[data-testid^="editor-remove-workout-"]').first().click();
  await expect(page.getByTestId("editor-confirm")).toContainText("из плана?");
  await page.getByTestId("editor-confirm-cancel").click();
  await expect(page.locator('[data-testid^="editor-remove-workout-"]')).toHaveCount(2);
  await page.locator('[data-testid^="editor-remove-workout-"]').first().click();
  await page.getByTestId("editor-confirm-ok").click();
  await expect(page.locator('[data-testid^="editor-remove-workout-"]')).toHaveCount(1);
  await expect(page.getByTestId("editor-total-1")).toHaveText("Всего 1");

  await page.reload();
  await page.getByRole("button", { name: "Планы" }).click();
  await page.getByTestId("plans-custom-plan-edit").click();
  await expect(page.getByTestId("editor-week-4")).toBeVisible();
  await expect(page.getByTestId("editor-total-3")).toHaveText("Всего 0");
  await expect(page.getByTestId("editor-total-1")).toHaveText("Всего 1");

  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});
