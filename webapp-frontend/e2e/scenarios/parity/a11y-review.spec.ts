import { expect, test } from "@playwright/test";

import { expectA11yClean, expectFocusRings } from "../../fixtures/a11y";
import { clickAndSync, noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import type { TelegramTheme } from "../../fixtures/telegramMock";

// #290 «Visual/a11y review (wave 13)»: сквозные проверки доступности на Live Session, Журнале, Планах и
// Поиске — контраст ≥ AA в светлой И тёмной темах, цели касания ≥ 44px, имена у кнопок, видимый фокус,
// шторка «+ Записать» (фокус внутрь, Escape, возврат фокуса). Seed: scripts/e2e_seed.py
// session_recovery (996101/996111/996121/996131) и journal_edit (99614x–99617x), каждый + retry (id+1).
const TITLE = "Тренировка восстановления";
const COMBOS = [
  { width: 320, theme: "light" as TelegramTheme, live: 996_101, journal: 996_141 },
  { width: 320, theme: "dark" as TelegramTheme, live: 996_111, journal: 996_151 },
  { width: 390, theme: "light" as TelegramTheme, live: 996_121, journal: 996_161 },
  { width: 390, theme: "dark" as TelegramTheme, live: 996_131, journal: 996_171 },
];
// Крупные карточки-обложки Главной/аналитики — чужие экраны (волна A), здесь не проверяем.
for (const { width, theme, live, journal } of COMBOS) {
  test.describe(`A11y review @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: width === 320 ? 640 : 844 } });
    test.setTimeout(120_000);

    test("Журнал: карточки, шторка записи и «+ Записать» — доступны с клавиатуры, контраст и цели ≥ 44px", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, journal + testInfo.retry, { theme });
      await openTab(page, "Журнал");
      await expect(page.getByTestId("journal-card").first()).toBeVisible();
      await expectA11yClean(page, "Журнал");
      await expectFocusRings(page, "Журнал");
      await expectNoHorizontalOverflow(page, "Журнал");

      // подписи нижней навигации не мельче 11px
      const tabFont = await page.locator(".bottom-tabbar-item > span").first().evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
      expect(tabFont).toBeGreaterThanOrEqual(11);

      await page.getByTestId("journal-card").first().click();
      await expect(page.getByTestId("journal-entry-sheet")).toBeVisible();
      await expectA11yClean(page, "Журнал: шторка записи");

      await page.getByRole("button", { name: "Отмена" }).click();
      const logButton = page.getByTestId("journal-log-button");
      await logButton.focus();
      await logButton.click();
      const sheet = page.getByTestId("journal-log-sheet");
      await expect(sheet).toBeVisible();
      await expect(sheet).toHaveAttribute("aria-modal", "true");
      await expect.poll(() => sheet.evaluate((el) => el.contains(document.activeElement))).toBe(true);
      await expectA11yClean(page, "Журнал: «+ Записать»");
      // Tab не уходит под шторку
      for (let i = 0; i < 5; i++) {
        await page.keyboard.press("Tab");
        expect(await sheet.evaluate((el) => el.contains(document.activeElement)), `Tab ${i + 1} вышел за шторку`).toBe(true);
      }
      await page.keyboard.press("Escape");
      await expect(sheet).toHaveCount(0);
      await expect(logButton).toBeFocused();

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("Поиск: чипы, закрыть, поле — цели ≥ 44px, контраст, видимый фокус", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, journal + testInfo.retry, { theme });
      await page.getByTestId("home-search-pill").click();
      await expect(page.getByTestId("search-screen")).toBeVisible();
      await page.getByRole("searchbox", { name: "Поиск" }).fill("Первая");
      await expectA11yClean(page, "Поиск");
      await expectFocusRings(page, "Поиск", 6);
      await expectNoHorizontalOverflow(page, "Поиск");
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("Планы + Live Session на всех фазах: контраст ≥ AA, цели ≥ 44px", async ({ page }, testInfo) => {
      page.on("dialog", (dialog) => void dialog.accept());
      const { consoleErrors, apiFailures } = await openAppAs(page, live + testInfo.retry, { theme });
      await page.getByTestId("my-workout-card").filter({ hasText: TITLE }).click();
      await page.getByRole("button", { name: "Добавить в план" }).click();
      await page.getByRole("button", { name: "Свободный пул" }).click();
      await page.getByRole("button", { name: "Добавить", exact: true }).click();
      await expect(page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${TITLE}`) }).first()).toBeVisible();
      await expectA11yClean(page, "Планы: неделя со строкой дня");
      await expectFocusRings(page, "Планы", 14);
      await expectNoHorizontalOverflow(page, "Планы");

      const group = page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${TITLE}`) }).first();
      await group.getByRole("button", { name: /^Начать: / }).click();
      await expectA11yClean(page, "Live: пред-экран");
      await page.getByRole("button", { name: "Начать", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Приготовься", exact: true, level: 2 })).toBeVisible();
      await expectA11yClean(page, "Live: приготовиться");

      await clickAndSync(page, "Готов", "/phase/next");
      await expect(page.getByRole("heading", { name: "Пошёл", exact: true, level: 2 })).toBeVisible();
      await expectA11yClean(page, "Live: работа");
      await page.getByLabel(/Результат|Секунды|Повторений/).fill("8");
      await page.getByTestId("log-panel-toggle").click();
      await expectA11yClean(page, "Live: работа, панель оценки");

      await clickAndSync(page, "Готово", "/sets:batch");
      await expect(page.getByRole("heading", { name: "Отдых", exact: true, level: 2 })).toBeVisible();
      await expectA11yClean(page, "Live: отдых");

      for (const reps of ["7", "6"]) {
        await clickAndSync(page, "Пропустить отдых", "/phase/next");
        await clickAndSync(page, "Готов", "/phase/next");
        await page.getByLabel(/Результат|Секунды|Повторений/).fill(reps);
        await clickAndSync(page, "Готово", "/sets:batch");
      }
      await expectA11yClean(page, "Live: план выполнен");
      await page.getByRole("button", { name: "Завершить", exact: true }).click();
      const review = page.getByTestId("workout-review");
      await expect(review).toBeVisible();
      await expectA11yClean(page, "Live: шторка итога");
      await review.getByTestId("workout-effort").getByRole("button").nth(2).click();
      await clickAndSync(page, "Сохранить и завершить", "/complete");
      await expect(page.getByText("Тренировка завершена")).toBeVisible();
      await expectA11yClean(page, "Live: итог");

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
