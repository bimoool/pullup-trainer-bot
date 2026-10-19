import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// «Отмена» и остановка плана — регрессии волны 3 (воспроизведено на staging dbf1e07, корневые причины в
// checkpoints/UX-EDITOR.md):
//  R1  «Остановить план» звала confirmAction → в клиенте без WebApp.showConfirm (Bot API < 6.2) / в iframe это
//      window.confirm = false: нажатие молча ничего не делало. Теперь подтверждение — лист в странице.
//  R2  остановленный план оставался в списке «Свои планы» с пометкой «остановлен» — выглядело как «не остановился».
//      Теперь он уходит из «Мой план по неделям» в «Завершённые».
// Сиды: ux_editor_journey 941023 (клиент 6.0 без showConfirm), ux_editor_fresh 941040 (отмены в формах).

test("R1/R2: клиент без showConfirm — остановка плана работает, план уходит из списка", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, 941_023, { telegram: { version: "6.0" } });
  await page.getByRole("button", { name: "Планы" }).click();
  await page.getByTestId("plans-custom-plan-stop").click();
  await expect(page.getByTestId("plans-stop-confirm")).toBeVisible();
  // фон листа тоже закрывает его без изменений
  await page.getByTestId("form-sheet-backdrop").click({ position: { x: 5, y: 5 } });
  await expect(page.getByTestId("plans-stop-confirm")).toHaveCount(0);
  await expect(page.getByTestId("plans-custom-section")).toContainText("Старый план");

  await page.getByTestId("plans-custom-plan-stop").click();
  await page.getByTestId("plans-stop-ok").click();
  await expect(page.getByTestId("plans-stop-confirm")).toHaveCount(0);
  await expect(page.getByTestId("plans-custom-section")).toHaveCount(0);
  await expect(page.getByTestId("plans-custom-plan-stop")).toHaveCount(0);
  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});

test("ошибка остановки показывается в листе, кнопка не залипает на «Останавливаю…»", async ({ page }) => {
  const { apiFailures } = await openAppAs(page, 941_024, { allowedApiStatuses: [500] });
  await page.route("**/api/v2/custom-plans/*/deactivate", (route) => route.fulfill({
    status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Сбой сервера" }),
  }));
  await page.getByRole("button", { name: "Планы" }).click();
  await page.getByTestId("plans-custom-plan-stop").click();
  await page.getByTestId("plans-stop-ok").click();
  await expect(page.getByTestId("plans-stop-error")).toContainText("Сбой сервера");
  await expect(page.getByTestId("plans-stop-ok")).toHaveText("Остановить план");
  await expect(page.getByTestId("plans-stop-ok")).toBeEnabled();
  await page.getByTestId("plans-stop-cancel").click();
  await expect(page.getByTestId("plans-custom-section")).toContainText("Старый план");
  void apiFailures;
});

test("отмены в формах: создание, редактор (удаление недели / убрать тренировку), расписание", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, 941_040);
  await page.getByRole("button", { name: "Планы" }).click();
  await page.getByTestId("plans-custom-plan").click();
  await page.getByTestId("plan-create-cancel").click(); // «Отмена» на шаге 1 → «Планы», ничего не создано
  await expect(page.getByTestId("plans-custom-section")).toHaveCount(0);

  await page.getByTestId("plans-custom-plan").click();
  await page.getByText("Тяга UX-А", { exact: true }).click();
  await page.getByText("Тяга UX-Б", { exact: true }).click();
  await page.getByTestId("plan-create-next").click();
  await page.getByTestId("plan-create-cancel").click(); // на шаге 2 это «Назад» к форме
  await expect(page.getByTestId("plan-create-name")).toBeVisible();
  await page.getByTestId("plan-create-next").click();
  await page.getByTestId("plan-create-save").click();
  await expect(page.getByTestId("plan-editor-screen")).toBeVisible();

  // удаление недели: Отмена и тап по фону не меняют план
  await page.getByTestId("editor-delete-3").click();
  await page.getByTestId("editor-confirm-cancel").click();
  await expect(page.getByTestId("editor-week-4")).toBeVisible();
  await page.getByTestId("editor-delete-3").click();
  await page.getByTestId("form-sheet-backdrop").click({ position: { x: 5, y: 5 } });
  await expect(page.getByTestId("editor-confirm")).toHaveCount(0);
  await expect(page.getByTestId("editor-week-4")).toBeVisible();
  // убрать тренировку: Отмена
  await page.locator('[data-testid^="editor-remove-workout-"]').first().click();
  await page.getByTestId("editor-confirm-cancel").click();
  await expect(page.locator('[data-testid^="editor-remove-workout-"]')).toHaveCount(2);
  // расписание: «Готово» возвращает в редактор без изменений
  await page.getByTestId("editor-schedule-2").click();
  await page.getByRole("button", { name: "Готово" }).click();
  await expect(page.getByTestId("plan-editor-screen")).toBeVisible();
  await expect(page.getByTestId("editor-total-2")).toHaveText("Всего 2");
  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});
