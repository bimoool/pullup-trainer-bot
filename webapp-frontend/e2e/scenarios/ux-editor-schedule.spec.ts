import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// UX-25: тренировка с количеством 2 ставится в один день дважды («×2», итог дня 2, «все занятия размещены»);
// перенос одного занятия на другой день обновляет оба итога; после перезагрузки раскладка та же.
// Неделя 2 — будущая (все дни доступны независимо от сегодняшнего). Сид: ux_editor_fresh 941002.
const TELEGRAM_ID = 941_002;
const A = "Тяга UX-А";

test("UX-25: ×2 в один день, итог дня, перенос, перезагрузка", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);
  await page.getByRole("button", { name: "Планы" }).click();
  await page.getByTestId("plans-custom-plan").click();
  await page.getByText(A).click();
  await page.getByTestId("custom-plan-save").click();
  await expect(page.getByTestId("plan-editor-screen")).toBeVisible();

  // неделя 2: A = 2 (старт 1)
  await page.getByRole("button", { name: `Больше: ${A}, неделя 2` }).click();
  await expect(page.getByTestId("editor-total-2")).toHaveText("Всего 2");
  await page.getByTestId("editor-schedule-2").click();
  await expect(page.getByTestId("week-schedule-screen")).toBeVisible();

  const workoutId = (await page.locator('[data-testid^="schedule-remaining-"]').first().getAttribute("data-testid"))!
    .replace("schedule-remaining-", "");
  const remaining = page.getByTestId(`schedule-remaining-${workoutId}`);
  const inc = (day: number) => page.getByTestId(`schedule-inc-${workoutId}-${day}`);
  const count = (day: number) => page.getByTestId(`schedule-count-${workoutId}-${day}`);

  await expect(remaining).toHaveText("осталось разместить 2");
  await inc(1).click(); // вторник
  await expect(count(1)).toHaveText("1");
  await expect(remaining).toHaveText("осталось разместить 1");
  await inc(1).click();
  await expect(count(1)).toHaveText("2");
  await expect(remaining).toHaveText("все занятия размещены");
  await expect(page.getByTestId("schedule-day-total-1")).toHaveText("Вт 2");
  await expect(page.getByText(`Вт ×2`)).toBeVisible();

  // квота исчерпана — сообщение, а не молчаливое игнорирование
  await inc(3).click();
  await expect(page.getByTestId("schedule-notice")).toHaveText("Все занятия размещены");

  // перенос одного занятия: Вт 2 → 1, Чт 0 → 1 (снятие — с подтверждением, Отмена ничего не меняет)
  await page.getByTestId(`schedule-dec-${workoutId}-1`).click();
  await page.getByTestId("schedule-confirm-cancel").click();
  await expect(count(1)).toHaveText("2");
  await page.getByTestId(`schedule-dec-${workoutId}-1`).click();
  await page.getByTestId("schedule-confirm-ok").click();
  await expect(count(1)).toHaveText("1");
  await inc(3).click();
  await expect(count(3)).toHaveText("1");
  await expect(page.getByTestId("schedule-day-total-1")).toHaveText("Вт 1");
  await expect(page.getByTestId("schedule-day-total-3")).toHaveText("Чт 1");

  // перезагрузка: та же раскладка
  await page.reload();
  await page.getByRole("button", { name: "Планы" }).click();
  await page.getByTestId("plans-custom-plan-edit").click();
  await page.getByTestId("editor-schedule-2").click();
  await expect(page.getByTestId("schedule-day-total-1")).toHaveText("Вт 1");
  await expect(page.getByTestId("schedule-day-total-3")).toHaveText("Чт 1");

  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});
