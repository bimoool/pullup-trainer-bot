import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py plan_week_grouping 900014 — прямой воспроизводящий
// сценарий бага Worker B (issue #188, checkpoint 2 review): RECURRING-курс
// с двумя PlanItem (Блок A / Блок Б), одна ProgramInclusion, оба
// day_of_week=NULL — ровно форма реального сида "Подтягивания". Плюс один
// ручной PlanItem (program_inclusion_id=NULL) для проверки, что он не
// слипается с группой.
const TELEGRAM_ID = 900_014;

// issue #304 (AD-4): одна строка плана = одно занятие. Курс из двух элементов (Блок A / Блок Б) одного
// дня — по-прежнему ОДНА тренировка (блоки A и Б вместе, без отдельных строк «Блок A»/«Блок Б»), но
// «× 3 в неделю» теперь три строки-занятия «Подтягивания (E2E group)», каждая «0/1»; ручная строка
// «× 2» — две своих строки, с курсом не слипаются.
test("«Планы»: курс A+Б одного дня — занятия-строки курса, без «Блок A»/«Блок Б», ручная — отдельно", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);

  const planResponsePromise = page.waitForResponse(
    (response) => response.url().includes("/api/v2/plan") && response.status() === 200,
  );

  await page.getByRole("button", { name: "Планы" }).click();

  const planResponse = await planResponsePromise;
  const plan = (await planResponse.json()).plan as {
    plan_items: {
      id: number; program_inclusion_id: number | null; day_of_week: number | null; occurrence_index: number | null;
    }[];
  };

  const course = plan.plan_items.filter((item) => item.program_inclusion_id !== null);
  expect(course.map((item) => item.occurrence_index)).toEqual([1, 2, 3]);
  expect(new Set(course.map((item) => item.day_of_week))).toEqual(new Set([null]));

  const weekRow = (name: string) => page.getByTestId("plans-row").filter({ hasText: name });
  await expect(page.getByText("Свободный пул")).toBeVisible();
  await expect(weekRow("Подтягивания (E2E group)")).toHaveCount(3);
  await expect(page.getByText("Блок A", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Блок Б", { exact: true })).toHaveCount(0);
  await expect(weekRow("Растяжка")).toHaveCount(plan.plan_items.length - course.length);

  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);

  await page.reload();
  await page.getByRole("button", { name: "Планы" }).click();
  await expect(weekRow("Подтягивания (E2E group)")).toHaveCount(3);
  await expect(page.getByText("Блок A", { exact: true })).toHaveCount(0);
});
