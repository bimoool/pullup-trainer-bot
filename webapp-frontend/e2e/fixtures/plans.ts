import { expect, type Locator, type Page } from "@playwright/test";

// «Планы» (#286 B): действия строки дня и плана живут в нижнем листе за кнопкой «⋯» —
// специ сначала открывают лист, потом выбирают пункт (смысл проверок не меняется).

export type RowAction = "Перенести" | "Редактировать тренировку" | "Убрать из плана";
export type PlanAction = "Скопировать неделю → на следующую" | "Убрать курс из плана";

/** Открыть лист «⋯» строки (первой, либо строки с заданным названием) и нажать пункт. */
export async function pickRowAction(page: Page, action: RowAction, title?: string | RegExp): Promise<void> {
  const row = title === undefined
    ? page.getByTestId("plans-row-more").first()
    : page.locator('[data-testid="plans-row"]').filter({ hasText: title }).getByTestId("plans-row-more");
  await row.click();
  await page.getByTestId("plans-row-sheet").getByRole("button", { name: action, exact: true }).click();
}

/** Открыть лист «⋯» плана (внутри scope — карточки курса, иначе первый на экране) и нажать пункт. */
export async function pickPlanAction(page: Page, action: PlanAction, scope?: Locator): Promise<void> {
  await (scope ?? page).getByTestId("plans-plan-more").first().click();
  await page.getByTestId("plans-plan-sheet").getByRole("button", { name: action, exact: true }).click();
}

/** Лист закрыт (ни строки, ни плана). */
export async function expectNoPlansSheet(page: Page): Promise<void> {
  await expect(page.getByRole("dialog")).toHaveCount(0);
}
