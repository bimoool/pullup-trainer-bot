import { expect, test, type Page } from "@playwright/test";

import { clickAndSync, noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import { pressTelegramBackButton } from "../../fixtures/telegramMock";

// Crimpd parity — residual gaps (#281): Журнал «Открыть тренировку» (J5), Главная «Все ›» по категории (H4),
// тесты в поиске + чип «Тесты» (D6), вибрация конца фазы таймера (R14).
// Seeds (scripts/e2e_seed_all.sh): workout_detail 9973{01,11} (+retry), home_discovery 9973{21,31} (только
// чтение, +retry), golden_journey 9974{01,11} (вибрация вкл.) и 9974{03,13} (выкл.), каждый + retry.
const USERS = {
  320: { journal: 997_301, home: 997_321, vibOn: 997_401, vibOff: 997_403, theme: "light" },
  390: { journal: 997_311, home: 997_331, vibOn: 997_411, vibOff: 997_413, theme: "dark" },
} as const;

type HapticWindow = { __haptics?: string[]; Telegram: { WebApp: { HapticFeedback: { notificationOccurred: (t: string) => void } } } };

/** Подменяет HapticFeedback из мока Telegram шпионом: вызовы копятся в window.__haptics. */
async function spyHaptics(page: Page) {
  await page.evaluate(() => {
    const w = window as unknown as HapticWindow;
    w.__haptics = [];
    w.Telegram.WebApp.HapticFeedback.notificationOccurred = (type) => void w.__haptics!.push(type);
  });
}
const hapticCount = (page: Page) => page.evaluate(() => (window as unknown as HapticWindow).__haptics?.length ?? 0);

/** «Золотая тренировка» → Workout Detail «Начать» → pre «Начать» → «Готов» → результат → «Готово» (отдых 2 с). */
async function playUntilRest(page: Page) {
  await page.getByTestId("my-workout-card").filter({ hasText: "Золотая тренировка" }).click();
  await page.getByTestId("workout-detail-start").click();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await expect(page.getByText("Живая тренировка")).toBeVisible();
  await clickAndSync(page, "Готов", "/phase/next");
  await page.getByLabel(/Результат|Секунды|Повторений/).fill("8");
  await clickAndSync(page, "Готово", "/sets:batch");
  await expect(page.getByRole("heading", { name: "Отдых", exact: true })).toBeVisible();
}

for (const width of WIDTHS) {
  const { journal, home, vibOn, vibOff, theme } = USERS[width as 320 | 390];
  test.describe(`Residual gaps @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 760 } });
    test.setTimeout(90_000);

    test("Журнал: «Открыть тренировку» ведёт в Workout Detail, «назад» возвращает в Журнал", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, journal + testInfo.retry, { theme, backButton: true });
      await openTab(page, "Журнал");
      const card = page.locator(".history-card").first();
      await expect(card).toBeVisible();
      await card.click();
      const open = page.getByTestId("journal-open-workout");
      await expect(open).toHaveText("Открыть тренировку");
      await expectNoHorizontalOverflow(page, "Журнал: запись с «Открыть тренировку»");

      await open.click();
      await expect(page.getByTestId("workout-detail")).toBeVisible();
      await expect(page.getByTestId("workout-detail-title")).toContainText("Очень длинная");
      await expect(page.getByTestId("workout-detail-history-row")).toHaveCount(2);
      await expectNoHorizontalOverflow(page, "Workout Detail из Журнала");

      // «Назад» (Telegram BackButton) — в Журнал на ту же открытую запись (#284 C1), не на Главную;
      // ещё один «назад» закрывает запись и показывает ленту.
      await pressTelegramBackButton(page);
      await expect(page.getByTestId("journal-open-workout")).toBeVisible();
      await expect(page.getByTestId("workout-detail")).toHaveCount(0);
      await pressTelegramBackButton(page);
      await expect(page.locator(".history-card").first()).toBeVisible();

      // Повторный заход на Главную не открывает старую тренировку.
      await openTab(page, "Главная");
      await expect(page.getByTestId("home-header")).toBeVisible();
      await expect(page.getByTestId("workout-detail")).toHaveCount(0);
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("Главная: «Все ›» у ряда категории открывает поиск по ней; у «Другое» кнопки нет", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, home + testInfo.retry, { theme });
      const row = page.getByTestId("program-category").filter({ hasText: "e2e_discovery_mobility" });
      await expect(row).toBeVisible();
      await expect(page.getByTestId("program-category").filter({ hasText: "Другое" }).getByTestId("program-category-all")).toHaveCount(0);
      await expectNoHorizontalOverflow(page, "Главная: ряд с «Все ›»");

      await row.getByTestId("program-category-all").click();
      await expect(page.getByTestId("search-screen")).toBeVisible();
      await expect(page.getByTestId("search-category-title")).toHaveText("e2e_discovery_mobility");
      await expect(page.getByTestId("search-chips").getByRole("button", { name: "e2e_discovery_mobility" })).toHaveAttribute("aria-pressed", "true");
      await expect(page.getByTestId("search-result-program")).toHaveCount(1);
      await expect(page.getByTestId("search-result-program")).toContainText("Дискавери: гибкость");
      await expect(page.getByTestId("search-result-test")).toHaveCount(0); // у тестов нет категории
      await expectNoHorizontalOverflow(page, "Поиск по категории");

      await page.getByTestId("search-chips").getByRole("button", { name: "Сбросить" }).click();
      await expect(page.getByTestId("search-category-title")).toHaveCount(0);
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("Поиск: тесты находятся по названию, чип «Тесты», деталь теста и возврат в поиск", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, home + testInfo.retry, { theme, backButton: true });
      await page.getByTestId("home-search-pill").click();
      const input = page.getByRole("searchbox", { name: "Поиск" });
      await input.fill("Максимум подтягиваний");
      await expect(page.getByTestId("search-result-test")).toHaveCount(1);
      await expect(page.getByTestId("search-result-test")).toContainText("Максимум подтягиваний");

      // Чип «Тесты»: только тесты (программы/тренировки/упражнения скрыты).
      await input.fill("");
      await page.getByTestId("search-chip-tests").click();
      await expect(page.getByTestId("search-chip-tests")).toHaveAttribute("aria-pressed", "true");
      expect(await page.getByTestId("search-result-test").count()).toBeGreaterThanOrEqual(3);
      await expect(page.getByTestId("search-result-program")).toHaveCount(0);
      await expect(page.getByTestId("search-result-exercise")).toHaveCount(0);
      await expectNoHorizontalOverflow(page, "Поиск: чип «Тесты»");

      // Деталь теста и возврат в тот же поиск (чип сохранён).
      await page.getByTestId("search-result-test").filter({ hasText: "Максимум подтягиваний" }).click();
      await expect(page.getByTestId("test-detail-title")).toHaveText("Максимум подтягиваний");
      await expectNoHorizontalOverflow(page, "Деталь теста из поиска");
      await pressTelegramBackButton(page);
      await expect(page.getByTestId("search-chip-tests")).toHaveAttribute("aria-pressed", "true");
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("вибрация: по умолчанию включена и срабатывает в конце фазы отдыха", async ({ page }, testInfo) => {
      page.on("dialog", (dialog) => void dialog.accept());
      const { consoleErrors, apiFailures } = await openAppAs(page, vibOn + testInfo.retry, { theme });
      await spyHaptics(page);
      await openTab(page, "Профиль");
      await page.getByTestId("profile-settings").click();
      await expect(page.getByTestId("settings-vibration")).toBeChecked();
      await expectNoHorizontalOverflow(page, "Настройки: вибрация");
      await page.getByRole("button", { name: "Отмена" }).click();
      await openTab(page, "Главная");

      await playUntilRest(page);
      await expect.poll(() => hapticCount(page), { timeout: 10_000 }).toBeGreaterThan(0);
      expect(await page.evaluate(() => (window as unknown as HapticWindow).__haptics![0])).toBe("success");
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("вибрация: выключатель в Настройках сохраняется и отключает сигнал", async ({ page }, testInfo) => {
      page.on("dialog", (dialog) => void dialog.accept());
      const { consoleErrors, apiFailures } = await openAppAs(page, vibOff + testInfo.retry, { theme });
      await spyHaptics(page);
      await openTab(page, "Профиль");
      await page.getByTestId("profile-settings").click();
      await page.getByTestId("settings-vibration").uncheck();
      await page.getByTestId("settings-save").click();
      await expect(page.getByTestId("settings-screen")).toHaveCount(0); // сохранено, экран закрылся

      // Перезагрузка: настройка устройства сохранилась.
      await page.reload();
      await spyHaptics(page);
      await openTab(page, "Профиль");
      await page.getByTestId("profile-settings").click();
      await expect(page.getByTestId("settings-vibration")).not.toBeChecked();
      await page.getByRole("button", { name: "Отмена" }).click();
      await openTab(page, "Главная");

      await playUntilRest(page);
      await page.waitForTimeout(3500); // отдых 2 с давно закончился
      expect(await hapticCount(page)).toBe(0);
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
