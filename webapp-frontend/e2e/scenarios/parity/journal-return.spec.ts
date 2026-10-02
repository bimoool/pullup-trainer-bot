import { expect, test } from "@playwright/test";

import { noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import { pressTelegramBackButton } from "../../fixtures/telegramMock";

// #284 C — Back из Журнала «Открыть тренировку» возвращает на тот же месяц и ту же открытую запись
// (раньше Журнал перемонтировался: сбрасывался на текущий месяц, деталь закрывалась).
// Seed: scripts/e2e_seed.py journal_return — сессии ПРЕДЫДУЩЕГО месяца (10-го, дважды 15-го, 20-го),
// привязанные к «Возвратная тренировка», и одна сессия сегодня. Тест только читает; +retry.
const USERS = { 320: { id: 999_701, theme: "light" }, 390: { id: 999_711, theme: "dark" } } as const;

for (const width of WIDTHS) {
  const { id, theme } = USERS[width as 320 | 390];
  test.describe(`Journal return @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 800 } });
    test.setTimeout(90_000);

    test("Back из «Открыть тренировку» — тот же месяц и та же запись", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, id + testInfo.retry, { theme, backButton: true });
      await openTab(page, "Журнал");
      await expect(page.locator(".history-card-clickable").first()).toBeVisible();

      const monthLabel = page.locator(".journal-month-label");
      const currentMonth = await monthLabel.innerText();
      await page.getByRole("button", { name: "Предыдущий месяц" }).click();
      await expect(monthLabel).not.toHaveText(currentMonth);
      const previousMonth = await monthLabel.innerText();
      const cards = page.locator(".history-card-clickable");
      await expect(cards).toHaveCount(4);

      // Две записи 15-го различаются подходами — открываем вторую в ленте и запоминаем её деталь.
      await cards.nth(1).click();
      const open = page.getByTestId("journal-open-workout");
      await expect(open).toBeVisible();
      const detailText = await page.locator("body").innerText();

      for (const round of [1, 2]) {
        await open.click();
        await expect(page.getByTestId("workout-detail-title")).toContainText("Возвратная тренировка");
        await expectNoHorizontalOverflow(page, `Workout Detail из Журнала (раунд ${round})`);

        await pressTelegramBackButton(page);
        // Тот же месяц (не текущий) и та же запись открыта.
        await expect(open).toBeVisible();
        await expect(page.getByTestId("workout-detail")).toHaveCount(0);
        expect(await page.locator("body").innerText()).toBe(detailText);
        await expectNoHorizontalOverflow(page, `Журнал: деталь после возврата (раунд ${round})`);
      }

      // Закрыв деталь, остаёмся в прошлом месяце: список прошлого месяца, не текущего.
      await pressTelegramBackButton(page);
      await expect(cards).toHaveCount(4);
      await expect(monthLabel).toHaveText(previousMonth);

      // Точка возврата одноразовая: заход на Журнал через вкладки — снова текущий месяц.
      await openTab(page, "Главная");
      await openTab(page, "Журнал");
      await expect(monthLabel).toHaveText(currentMonth);

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
