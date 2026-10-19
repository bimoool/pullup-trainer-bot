import { expect, type Page } from "@playwright/test";

// Общее тело сквозного сценария владельца (волна 3): используется Telegram-проектом (ux-editor-journey.spec.ts)
// и браузерным (web/ux-editor-journey.spec.ts) — один и тот же путь через настоящие кнопки вкладки «Планы».
// Сид: ux_editor_journey (план [А, Б] × [2, 2, 0, 2]; в неделе 1 одно занятие А выполнено; есть история в Журнале).
// Дни недели — только воскресенье (6) и неделя 2 (все дни), чтобы сценарий не зависел от дня запуска.
export const A = "Тяга UX-А";
const B = "Тяга UX-Б";

export async function openPlans(page: Page) {
  await page.getByRole("button", { name: "Планы" }).click();
  await expect(page.getByText("Текущий план", { exact: true })).toBeVisible();
}

export async function runOwnerJourney(page: Page): Promise<void> {
  await openPlans(page);

  // --- (1) старый план: отдельная карточка «Мой план по неделям», остановка с подтверждением ---
  const section = page.getByTestId("plans-custom-section");
  await expect(section).toContainText("Старый план");
  await expect(section).toContainText("Занятий по неделям: 2 · 2 · 0 · 2");
  await expect(page.getByTestId("plans-row")).toHaveCount(2); // неделя 1: А (выполнено) и Б

  await page.getByTestId("plans-custom-plan-stop").click();
  const stopText = page.getByTestId("plans-stop-text");
  await expect(stopText).toContainText("Это остановка, а не удаление");
  await expect(stopText).toContainText("Будущие невыполненные занятия этого плана будут убраны из плана");
  await expect(stopText).toContainText("Выполненные занятия, история в Журнале и сами тренировки останутся");

  // «Отмена» ничего не меняет
  await page.getByTestId("plans-stop-cancel").click();
  await expect(page.getByTestId("plans-stop-confirm")).toHaveCount(0);
  await expect(section).toContainText("Старый план");
  await expect(page.getByTestId("plans-row")).toHaveCount(2);

  // подтверждение: план уходит из «Мой план», открытое занятие Б снято, выполненное А и история остаются
  await page.getByTestId("plans-custom-plan-stop").click();
  await page.getByTestId("plans-stop-ok").click();
  await expect(page.getByTestId("plans-stop-confirm")).toHaveCount(0);
  await expect(page.getByTestId("plans-custom-section")).toHaveCount(0);
  await expect(page.getByTestId("plans-row")).toHaveCount(1);
  await expect(page.getByTestId("plans-row").first()).toContainText(A);
  await expect(page.getByTestId("plan-item-counter").first()).toHaveText("1/1");
  await page.getByRole("tab", { name: "Завершённые" }).click();
  await expect(page.getByTestId("plans-completed-custom-row")).toContainText("Старый план");
  await expect(page.getByTestId("plans-completed-custom-row")).toContainText("Выполненные занятия сохранены");
  await page.getByRole("tab", { name: "Сейчас" }).click();
  await page.getByRole("button", { name: "Журнал" }).click();
  await expect(page.getByText(A, { exact: true }).first()).toBeVisible();

  // --- (2) создание через новый редактор; «Отмена» на форме возвращает без изменений ---
  await openPlans(page);
  await page.getByTestId("plans-custom-plan").click();
  await expect(page.getByTestId("plan-create-screen")).toBeVisible();
  await page.getByTestId("plan-create-cancel").click();
  await expect(page.getByTestId("plan-create-screen")).toHaveCount(0);
  await expect(page.getByTestId("plans-custom-section")).toHaveCount(0);

  await page.getByTestId("plans-custom-plan").click();
  await page.getByTestId("plan-create-name").fill("Мой новый");
  await page.getByText(A, { exact: true }).click();
  await page.getByText(B, { exact: true }).click();
  await page.getByRole("button", { name: "Меньше недель" }).click();
  await page.getByRole("button", { name: "Меньше недель" }).click();
  await expect(page.getByTestId("plan-create-weeks")).toHaveText("2");
  await page.getByTestId("plan-create-next").click();
  // 1 + 1 по умолчанию; неделя 1: А = 2 (всего 3); неделя 2: Б = 0 (всего 1)
  await page.getByRole("button", { name: `Больше: ${A}, неделя 1` }).click();
  await expect(page.getByTestId("create-total-1")).toHaveText("Всего 3");
  await page.getByRole("button", { name: `Меньше: ${B}, неделя 2` }).click();
  await expect(page.getByTestId("create-total-2")).toHaveText("Всего 1");
  // «Назад» возвращает к форме без потери введённого
  await page.getByTestId("plan-create-cancel").click();
  await expect(page.getByTestId("plan-create-name")).toHaveValue("Мой новый");
  await page.getByTestId("plan-create-next").click();
  await expect(page.getByTestId("create-total-1")).toHaveText("Всего 3");
  await page.getByTestId("plan-create-save").click();

  await expect(page.getByTestId("plan-editor-screen")).toBeVisible();
  await expect(page.getByTestId("editor-total-1")).toHaveText("Всего 3");
  await expect(page.getByTestId("editor-total-2")).toHaveText("Всего 1");

  // --- (3) расписание: А дважды в воскресенье + Б в воскресенье; неделя 2: А в среду ---
  await page.getByTestId("editor-schedule-1").click();
  const aRemaining = page.locator('[data-testid^="schedule-remaining-"]').first();
  const aId = (await aRemaining.getAttribute("data-testid"))!.replace("schedule-remaining-", "");
  const bId = (await page.locator('[data-testid^="schedule-remaining-"]').nth(1).getAttribute("data-testid"))!.replace("schedule-remaining-", "");
  await page.getByTestId(`schedule-inc-${aId}-6`).click();
  await expect(page.getByTestId(`schedule-count-${aId}-6`)).toHaveText("1");
  await page.getByTestId(`schedule-inc-${aId}-6`).click();
  await expect(page.getByTestId(`schedule-count-${aId}-6`)).toHaveText("2");
  await expect(page.getByTestId(`schedule-remaining-${aId}`)).toHaveText("все занятия размещены");
  await page.getByTestId(`schedule-inc-${bId}-6`).click();
  await expect(page.getByTestId("schedule-day-total-6")).toHaveText("Вс 3");
  await page.getByRole("button", { name: "Готово" }).click();
  await page.getByTestId("editor-schedule-2").click();
  await page.getByTestId(`schedule-inc-${aId}-2`).click();
  await expect(page.getByTestId("schedule-day-total-2")).toHaveText("Ср 1");
  await page.getByRole("button", { name: "Готово" }).click();
  await page.getByRole("button", { name: "Готово" }).click(); // из редактора на «Планы»

  // --- (4) уйти на Главную, вернуться, перезагрузить, открыть сохранённый план ---
  await page.getByRole("button", { name: "Главная" }).click();
  await openPlans(page);
  await page.reload();
  await openPlans(page);
  await expect(page.getByTestId("plans-custom-section")).toContainText("Мой новый");
  await expect(page.getByTestId("plans-custom-section")).toContainText("Занятий по неделям: 3 · 1");
  await page.getByTestId("plans-custom-plan-edit").click();
  await expect(page.getByTestId("editor-total-1")).toHaveText("Всего 3");
  await expect(page.getByTestId("editor-total-2")).toHaveText("Всего 1");
  await page.getByTestId("editor-schedule-1").click();
  await expect(page.getByTestId(`schedule-count-${aId}-6`)).toHaveText("2");
  await expect(page.getByTestId(`schedule-count-${bId}-6`)).toHaveText("1");
  await expect(page.getByTestId("schedule-day-total-6")).toHaveText("Вс 3");
  await page.getByRole("button", { name: "Готово" }).click();
  await page.getByTestId("editor-schedule-2").click();
  await expect(page.getByTestId(`schedule-count-${aId}-2`)).toHaveText("1");
  await page.getByRole("button", { name: "Готово" }).click();
  await page.getByRole("button", { name: "Готово" }).click();

  // --- (5) замена активного плана: подтверждение называет план; «Отмена» ничего не создаёт ---
  await page.getByTestId("plans-custom-plan").click();
  await page.getByTestId("plan-create-name").fill("Третий");
  await page.getByText(A, { exact: true }).click();
  await page.getByTestId("plan-create-next").click();
  await page.getByTestId("plan-create-save").click();
  const confirm = page.getByTestId("plan-replace-confirm");
  await expect(confirm).toContainText("У вас уже есть план «Мой новый». Новый заменит его: будущие занятия «Мой новый» будут сняты, история сохранится.");
  await page.getByTestId("plan-replace-cancel").click();
  await expect(confirm).toHaveCount(0);
  await expect(page.getByTestId("plan-create-screen")).toBeVisible();
  await page.getByTestId("plan-create-save").click();
  await page.getByTestId("plan-replace-ok").click();
  await expect(page.getByTestId("plan-editor-screen")).toBeVisible();
  await page.getByRole("button", { name: "Готово" }).click();
  await expect(page.getByTestId("plans-custom-section")).toContainText("Третий");
  await expect(page.getByTestId("plans-custom-section")).not.toContainText("Мой новый");
  await page.getByRole("tab", { name: "Завершённые" }).click();
  await expect(page.getByTestId("plans-completed-custom-row")).toHaveCount(2); // «Старый план» и «Мой новый»

}
