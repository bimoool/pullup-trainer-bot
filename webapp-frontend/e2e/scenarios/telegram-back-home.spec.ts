import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";
import { isTelegramBackButtonVisible, pressTelegramBackButton } from "../fixtures/telegramMock";

/**
 * Аудит staging 6475bc0: Telegram «Назад» на Главной. Стек BackButton считал кнопку скрытой с самого старта и прятал
 * её, только если сам же показал: если клиент оставил кнопку видимой (перезагрузка Mini App с открытого вложенного
 * экрана, гонка показа/скрытия), на Главной висела «Назад» без обработчика — нажатие ничего не делало.
 * Теперь при старте приложение один раз приводит кнопку к состоянию стека (на Главной — скрыта).
 * Сид: ready 900003 (только чтение). 320 и 375 px.
 */
for (const width of [320, 375]) {
  test.describe(`${width}px`, () => {
    test.use({ viewport: { width, height: 640 }, isMobile: true, hasTouch: true });

    test(`${width}px: на Главной после старта Telegram «Назад» скрыта, навигация «вглубь-назад» работает`, async ({ page }) => {
      // Клиент оставил кнопку видимой (как после перезагрузки с вложенного экрана).
      await page.addInitScript(() => {
        (window as unknown as { __tgBackButtonVisible: boolean }).__tgBackButtonVisible = true;
      });
      const { apiFailures } = await openAppAs(page, 900_003, { backButton: true });
      await expect(page.getByRole("button", { name: "Главная" })).toBeVisible();
      await expect.poll(() => isTelegramBackButtonVisible(page), { timeout: 5_000 }).toBe(false);

      // Обычный цикл: вложенный экран показывает «Назад», нажатие возвращает на Главную и прячет кнопку.
      await page.getByRole("button", { name: "Профиль" }).click();
      await page.getByTestId("profile-weight").click();
      await expect.poll(() => isTelegramBackButtonVisible(page)).toBe(true);
      await pressTelegramBackButton(page);
      await expect.poll(() => isTelegramBackButtonVisible(page)).toBe(false);
      expect(apiFailures).toEqual([]);
    });
  });
}
