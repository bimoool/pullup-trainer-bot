import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

/**
 * Аудит staging 6475bc0: «+ Добавить упражнение» открывало форму под всеми неделями — на телефоне ниже экрана,
 * нажатие выглядело как «ничего не произошло». Форма должна оказаться в видимой области и получить фокус.
 * Сид: plan_week_grouping 900014 (форму только открываем и закрываем). 320 и 375 px.
 */
for (const width of [320, 375]) {
  test.describe(`${width}px`, () => {
    test.use({ viewport: { width, height: 640 }, isMobile: true, hasTouch: true });

    test(`${width}px: форма «Добавить упражнение» открывается в видимой области`, async ({ page }) => {
      const { apiFailures } = await openAppAs(page, 900_014);
      await page.getByRole("button", { name: "Планы" }).click();
      const add = page.getByRole("button", { name: "+ Добавить упражнение" }).first();
      await add.scrollIntoViewIfNeeded();
      await add.click();
      // Заголовок формы появился в DOM и виден без прокрутки (на старом коде — ниже экрана).
      const heading = page.getByText("Добавить упражнение", { exact: true }).last();
      await expect(heading).toBeAttached();
      await expect(heading).toBeInViewport();
      // …и не спрятан под нижней навигацией: в центре заголовка — сам заголовок, а не таб-бар.
      const headingOnTop = await heading.evaluate((element) => {
        const box = element.getBoundingClientRect();
        const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
        return hit !== null && (element === hit || element.contains(hit));
      });
      expect(headingOnTop, "заголовок формы перекрыт нижней навигацией или вне экрана").toBe(true);
      const form = page.getByTestId("plan-add-exercise-form");
      await expect(form).toBeFocused();
      await expect(form).toBeInViewport({ ratio: 0.3 });
      await form.getByRole("button", { name: "Отмена" }).click();
      await expect(form).toHaveCount(0);
      expect(apiFailures).toEqual([]);
    });
  });
}
