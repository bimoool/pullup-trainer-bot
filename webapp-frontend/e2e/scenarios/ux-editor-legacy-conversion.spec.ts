import { expect, test, type Page } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// Старый свой план (spec = NULL, ротация [А, Б], объём [2,2,0,2]) открывается в редакторе без изменения того, что
// видно в плане: те же занятия (id) до и после первой правки ДРУГОЙ недели. Сид: ux_editor_legacy 941010.
// Числа вручную: ротация А,Б → А=[1,1,0,1], Б=[1,1,0,1], итоги 2/2/0/2; правка недели 3 (А=1) → 2/2/1/2.
const TELEGRAM_ID = 941_010;

type PlanItem = { id: number; custom_plan_id: number | null; plan_week_id: number | null; status?: string };

async function openPlansAndCapture(page: Page): Promise<number[]> {
  const responsePromise = page.waitForResponse((r) => r.url().includes("/api/v2/plan") && r.status() === 200);
  await page.getByRole("button", { name: "Планы" }).click();
  const plan = (await (await responsePromise).json()).plan as { plan_items: PlanItem[] };
  return plan.plan_items.filter((item) => item.custom_plan_id !== null).map((item) => item.id).sort((a, b) => a - b);
}

test("старый план: редактор показывает ту же раскладку, правка другой недели не трогает прежние занятия", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);
  const before = await openPlansAndCapture(page);
  expect(before).toHaveLength(6); // 2 + 2 + 0 + 2

  await page.getByTestId("plans-custom-plan-edit").click();
  await expect(page.getByTestId("plan-editor-screen")).toBeVisible();
  const totals = await Promise.all([1, 2, 3, 4].map(async (w) => (await page.getByTestId(`editor-total-${w}`).innerText()).trim()));
  expect(totals).toEqual(["Всего 2", "Всего 2", "Всего 0", "Всего 2"]);
  await expect(page.getByTestId("editor-rest-note-3")).toHaveText("Неделя отдыха по плану");
  await expect(page.getByTestId(`editor-qty-1-${await firstWorkoutId(page)}`)).toHaveText("1");

  // правка недели 3: А = 1 → неделя перестаёт быть пустой, итоги 2/2/1/2
  await page.getByRole("button", { name: "Больше: Тяга UX-А, неделя 3" }).click();
  await expect(page.getByTestId("editor-total-3")).toHaveText("Всего 1");

  await page.getByRole("button", { name: "Готово" }).click();
  await page.reload();
  const after = await openPlansAndCapture(page);
  // прежние шесть занятий на месте (те же id), добавилось ровно одно новое
  expect(after.filter((id) => before.includes(id))).toEqual(before);
  expect(after).toHaveLength(7);

  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});

async function firstWorkoutId(page: Page): Promise<string> {
  const testId = await page.locator('[data-testid^="editor-remove-workout-"]').first().getAttribute("data-testid");
  return testId!.replace("editor-remove-workout-", "");
}
