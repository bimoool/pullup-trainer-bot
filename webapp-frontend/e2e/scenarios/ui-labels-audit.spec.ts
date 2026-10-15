import { expect, test } from "@playwright/test";

import { openTab } from "../fixtures/parity";
import { openAppAs } from "../fixtures/setup";
import { pressTelegramBackButton } from "../fixtures/telegramMock";

/**
 * Аудит staging 6475bc0 — подписи и иконки (только чтение, сид ready 900003; каталог готовых тренировок и тестов —
 * системный контент миграций). 320 и 375 px.
 *  - деталь ГОТОВОЙ тренировки подписывалась «Своя тренировка» (строка была зашита для всех);
 *  - баннер Главной создаёт тренировку, а назывался «Своя программа» / «собрать свой комплекс»;
 *  - карточки тестов в Профиле показывали два шеврона (иконка chevronRight + CSS ::after «›»); остаётся ::after.
 */
for (const width of [320, 375]) {
  test.describe(`${width}px`, () => {
    test.use({ viewport: { width, height: 760 }, isMobile: true, hasTouch: true });

    test(`${width}px: «Своя/Готовая», баннер создания тренировки, один шеврон`, async ({ page }) => {
      const { apiFailures } = await openAppAs(page, 900_003, { backButton: true });

      await expect(page.getByRole("button", { name: "Баннер: собрать свою тренировку" })).toContainText("Своя тренировка");

      // Строка «Тесты» на Главной: шеврон один — в тексте; CSS ::after там отключён (shell.css), не дубль.
      const homeTests = page.getByTestId("home-tests-row");
      await expect(homeTests).toContainText("›");
      expect(await homeTests.evaluate((element) => getComputedStyle(element, "::after").content)).toMatch(/^(none|normal)$/);

      await page.getByTestId("system-workout-card").first().click();
      await expect(page.getByTestId("workout-detail-subtitle")).toHaveText("Готовая тренировка");
      await pressTelegramBackButton(page);

      await openTab(page, "Профиль");
      const card = page.getByTestId("profile-tests").getByTestId("test-card").first();
      // Ровно одна видимая стрелка: ::after «›» плоского списка Профиля, иконка карточки скрыта.
      expect(await card.evaluate((element) => getComputedStyle(element, "::after").content)).toContain("›");
      await expect(card.locator(".test-card-chevron")).toBeHidden();
      expect(apiFailures).toEqual([]);
    });
  });
}
