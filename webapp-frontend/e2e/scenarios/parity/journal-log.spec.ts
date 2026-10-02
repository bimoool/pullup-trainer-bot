import { expect, test } from "@playwright/test";

import { noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, openJournalEntry, openTab, selectMetric, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";

// Crimpd parity — Journal log (#263). Moved out of crimpd-parity.spec.ts into its own file
// (scenarios/parity/README.md) so parallel parity tasks do not conflict on one shared tail.

// --- Journal log (#263): «+ Записать» — тренировка задним числом и свободная активность ----------
// Seed: scripts/e2e_seed.py golden_journey — своя Workout «Золотая тренировка» (reps 2 x 8), пустой
// Журнал. Тест пишет сессии, поэтому по пользователю на ширину/тему и на retry (id + retry);
// второй тест (Главная → «+») берёт id + 5 + retry.
const LOG_USERS = { 320: { id: 985_001, theme: "light" }, 390: { id: 985_011, theme: "dark" } } as const;

function localDateOffset(offsetDays: number) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

for (const width of WIDTHS) {
  const { id, theme } = LOG_USERS[width as 320 | 390];
  test.describe(`Journal log @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 800 } });
    test.setTimeout(90_000);

    test("шторка → свободная активность и тренировка из моих появляются в Журнале и Аналитике", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, id + testInfo.retry, { theme });
      await openTab(page, "Журнал");
      const yesterday = localDateOffset(-1);
      const tomorrow = localDateOffset(1);
      const cards = page.locator(".history-card-clickable");

      // Шторка из Журнала: два пути.
      await page.getByTestId("journal-log-button").click();
      await expect(page.getByTestId("journal-log-sheet")).toBeVisible();
      await expect(page.getByTestId("log-option-workout")).toHaveText("Тренировку из моих");
      await expect(page.getByTestId("log-option-activity")).toHaveText("Другую активность");
      await expectNoHorizontalOverflow(page, "Журнал: шторка «Записать»");

      // Другая активность: валидация (длительность, будущая дата), затем сохранение.
      await page.getByTestId("log-option-activity").click();
      await expect(page.getByTestId("log-activity-type").locator("option")).toHaveText([
        "Бег", "Велосипед", "Плавание", "Ходьба/хайкинг", "Йога/растяжка", "Силовая в зале", "Единоборства", "Другое",
      ]);
      await expectNoHorizontalOverflow(page, "Журнал: форма активности");
      await page.getByTestId("log-duration").fill("0:00");
      await page.getByTestId("log-save").click();
      await expect(page.getByTestId("log-error")).toContainText("Длительность");
      await page.getByTestId("log-duration").fill("13:00");
      await page.getByTestId("log-save").click();
      await expect(page.getByTestId("log-error")).toContainText("Длительность");
      await page.getByTestId("log-date").evaluate((element, value) => {
        const input = element as HTMLInputElement;
        input.removeAttribute("max");
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
        setter.call(input, value);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }, tomorrow);
      await page.getByTestId("log-duration").fill("1:15");
      await page.getByTestId("log-save").click();
      await expect(page.getByTestId("log-error")).toContainText("в будущем");
      await page.getByTestId("log-date").fill(yesterday);
      await page.getByTestId("log-activity-type").selectOption("swimming");
      await page.getByTestId("log-effort-3").click();
      await page.getByTestId("log-note").fill("бассейн");
      await page.getByTestId("log-save").click();

      // Карточка: тип и длительность; календарь показывает день с точкой.
      const activityCard = cards.filter({ hasText: "Плавание" });
      await expect(activityCard).toHaveCount(1);
      await expect(activityCard.getByTestId("journal-activity-duration")).toHaveText("1:15");
      await expect(activityCard.locator(".journal-stat[data-stat=\"duration\"] .journal-stat-label")).toHaveText("Длительность");
      await expect(activityCard.locator(".journal-stat[data-stat=\"distance\"] .journal-stat-value")).toHaveText("—");
      await expect(activityCard.getByTestId("journal-card-effort")).toHaveText("3");
      await expectNoHorizontalOverflow(page, "Журнал: карточка активности");
      await page.locator(".journal-month-label").click();
      await expect(page.locator(`[data-date="${yesterday}"][data-has-training="true"]`)).toBeVisible();

      // Тренировка из моих: выбор, значения подходов, усилие.
      await page.getByTestId("journal-log-button").click();
      await page.getByTestId("log-option-workout").click();
      await page.getByTestId("log-save").click();
      await expect(page.getByTestId("log-error")).toContainText("подход");
      await page.getByTestId("log-workout-select").selectOption({ label: "Золотая тренировка" });
      await expect(page.getByTestId("log-exercise")).toHaveCount(1);
      await page.getByTestId("log-date").fill(yesterday);
      const setInputs = page.locator('[data-testid^="log-set-"]');
      await expect(setInputs).toHaveCount(2);
      await setInputs.nth(0).fill("8");
      await setInputs.nth(1).fill("7");
      await page.getByTestId("log-effort-4").click();
      await page.getByTestId("log-note").fill("без таймера");
      await expectNoHorizontalOverflow(page, "Журнал: форма тренировки");
      await page.getByTestId("log-save").click();

      const backdatedCard = cards.filter({ hasText: "Записана задним числом" });
      await expect(backdatedCard).toHaveCount(1);
      // карточка — суммы (#286): 2 подхода, 15 повторов, усилие 4; факт по подходам «8 · 7» — в деталях записи
      await expect(backdatedCard.locator('.journal-stat[data-stat="sets"] .journal-stat-value')).toHaveText("2");
      await expect(backdatedCard.locator('.journal-stat[data-stat="reps"] .journal-stat-value')).toHaveText("15");
      await expect(backdatedCard.getByTestId("journal-card-effort")).toHaveText("4");
      await expect(cards).toHaveCount(2);
      await openJournalEntry(page, backdatedCard);
      await expect(page.getByText("Факт: 8 · 7")).toBeVisible();
      await expect(page.getByTestId("journal-workout-effort")).toContainText("4 Тяжело");
      await expect(page.getByTestId("journal-workout-comment")).toContainText("без таймера");
      await page.getByRole("button", { name: "← Назад" }).click();

      // Аналитика: обе записи — тренировки, минуты считаются только по свободной активности.
      await openTab(page, "Аналитика");
      const card = page.getByTestId("analytics-metrics");
      const total = page.getByTestId("analytics-metric-total");
      await expect(total).toContainText("Всего тренировок: 2");
      await selectMetric(page, "Минуты");
      await expect(total).toContainText("Всего минут: 1 ч 15 мин");
      await expect(page.getByTestId("analytics-no-duration")).toHaveText("без данных о времени: 1");

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("«+» на Главной ведёт в Журнал со шторкой записи", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, id + 5 + testInfo.retry, { theme });
      await page.getByTestId("home-plus").click();
      await page.getByTestId("home-sheet-log").click();
      await expect(page.getByTestId("journal-log-sheet")).toBeVisible();
      await expectNoHorizontalOverflow(page, "Журнал: шторка с Главной");
      await page.getByTestId("log-option-activity").click();
      await expect(page.getByTestId("journal-log-form")).toBeVisible();
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
