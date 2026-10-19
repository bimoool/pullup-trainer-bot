import { expect, test, type Page } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// UX-24: создать план на 4 недели, A = 2/2/0/1, B = 1/1/1/1 → итоги по неделям 3/3/1/2 (посчитано вручную:
// 2+1, 2+1, 0+1, 1+1); после перезагрузки редактор показывает то же самое. Сид: ux_editor_fresh 941001.
const TELEGRAM_ID = 941_001;

async function totals(page: Page): Promise<string[]> {
  return Promise.all([1, 2, 3, 4].map(async (week) => (await page.getByTestId(`editor-total-${week}`).innerText()).trim()));
}

test("UX-24: план на 4 недели с количествами по неделям, итоги и перезагрузка", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);
  await page.getByRole("button", { name: "Планы" }).click();
  await page.getByTestId("plans-custom-plan").click();

  await page.getByText("Тяга UX-А").click();
  await page.getByText("Тяга UX-Б").click();
  await expect(page.getByTestId("plan-create-weeks")).toHaveText("4");
  await page.getByTestId("plan-create-next").click();
  await page.getByTestId("plan-create-save").click();

  await expect(page.getByTestId("plan-editor-screen")).toBeVisible();
  // старт: по одному занятию каждой тренировки в неделю → итоги 2/2/2/2
  expect(await totals(page)).toEqual(["Всего 2", "Всего 2", "Всего 2", "Всего 2"]);

  const inc = (title: string, week: number) => page.getByRole("button", { name: `Больше: ${title}, неделя ${week}` });
  const dec = (title: string, week: number) => page.getByRole("button", { name: `Меньше: ${title}, неделя ${week}` });

  // A: 1/1/1/1 → 2/2/0/1
  await inc("Тяга UX-А", 1).click();
  await expect(page.getByTestId("editor-total-1")).toHaveText("Всего 3");
  await inc("Тяга UX-А", 2).click();
  await expect(page.getByTestId("editor-total-2")).toHaveText("Всего 3");
  await dec("Тяга UX-А", 3).click();
  await expect(page.getByTestId("editor-total-3")).toHaveText("Всего 1");
  await expect(page.getByTestId("editor-rest-note-3")).toHaveCount(0); // 1 занятие — это не неделя отдыха

  expect(await totals(page)).toEqual(["Всего 3", "Всего 3", "Всего 1", "Всего 2"]);

  // нулевая неделя подписана: убираем и B из недели 3 → 0
  await dec("Тяга UX-Б", 3).click();
  await expect(page.getByTestId("editor-rest-note-3")).toHaveText("Неделя отдыха по плану");
  await inc("Тяга UX-Б", 3).click();
  await expect(page.getByTestId("editor-total-3")).toHaveText("Всего 1");

  // перезагрузка: те же итоги
  await page.reload();
  await page.getByRole("button", { name: "Планы" }).click();
  await page.getByTestId("plans-custom-plan-edit").click();
  expect(await totals(page)).toEqual(["Всего 3", "Всего 3", "Всего 1", "Всего 2"]);

  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});
