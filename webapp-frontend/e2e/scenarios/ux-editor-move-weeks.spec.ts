import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// UX-31 / перенос между неделями: у занятия текущей недели есть «⋯» (те же действия, что в будущих неделях),
// лист переноса имеет «Отмена» (она ничего не меняет); перенос на неделю 2 / среда виден на неделе 2.
// Сид: ux_editor_fresh 941003.
const TELEGRAM_ID = 941_003;

test("UX-31: «⋯» в текущей неделе, Отмена не меняет, перенос в следующую неделю", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);
  await page.getByRole("button", { name: "Планы" }).click();
  await page.getByTestId("plans-custom-plan").click();
  await page.getByText("Тяга UX-А").click();
  await page.getByTestId("custom-plan-save").click();
  await expect(page.getByTestId("plan-editor-screen")).toBeVisible();
  await page.getByRole("button", { name: "Готово" }).click();

  const row = page.getByTestId("plans-row").first();
  await expect(row).toContainText("Тяга UX-А");
  const more = row.getByTestId("plans-row-more");
  await expect(more).toBeVisible();

  // Отмена на листе переноса: ничего не меняется
  await more.click();
  await page.getByTestId("plans-sheet-move").click();
  await page.getByTestId("move-cancel").click();
  await expect(page.getByTestId("plans-row")).toHaveCount(1);

  // Перенос на неделю 2, среда
  await row.getByTestId("plans-row-more").click();
  await page.getByTestId("plans-sheet-move").click();
  await page.getByRole("button", { name: /^Неделя 2 · / }).click();
  await page.getByRole("button", { name: "Ср", exact: true }).click();
  await page.getByRole("button", { name: "Сохранить" }).click();

  await expect(page.getByTestId("plans-row")).toHaveCount(0);
  await page.getByRole("button", { name: "Следующая неделя" }).click();
  const moved = page.getByTestId("plans-row");
  await expect(moved.first()).toContainText("Тяга UX-А");
  await expect(page.getByText("Среда", { exact: true })).toBeVisible();
  // в неделе 2 теперь два занятия этой тренировки: плановое и перенесённое
  await expect(moved).toHaveCount(2);

  await page.reload();
  await page.getByRole("button", { name: "Планы" }).click();
  await page.getByRole("button", { name: "Следующая неделя" }).click();
  await expect(page.getByTestId("plans-row")).toHaveCount(2);

  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});
