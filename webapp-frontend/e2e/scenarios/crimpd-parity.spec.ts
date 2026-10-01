import { expect, test, type Page } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// Crimpd 8.5.x full-parity contract (docs/CRIMPD_FULL_PARITY_8_5.md).
//
// One focused, growing suite — NOT a copy of the other specs. Every parity issue
// ("CRIMPD P0/P1/P2 — …") adds its own `test.describe("<area>")` block here proving the
// user-visible capability it delivers, at representative mobile widths. The final QA issue
// extends the whole file to light/dark and empty/populated users.
//
// Baseline block below pins what is reachable today, so later blocks can only add surface.
// Read-only user: `ready` (scripts/e2e_seed.py ready 900003).
const READY_USER = 900_003;
const WIDTHS = [320, 390];

async function expectNoHorizontalOverflow(page: Page, where: string) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth, `горизонтальный overflow на «${where}»`).toBeLessThanOrEqual(clientWidth);
}

async function openTab(page: Page, label: string) {
  await page.locator(".bottom-tabbar").getByRole("button", { name: label }).click();
}

for (const width of WIDTHS) {
  test.describe(`Baseline surface @${width}px`, () => {
    test.use({ viewport: { width, height: 760 } });

    test("пять вкладок открываются и показывают основное содержимое", async ({ page }) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, READY_USER);

      // Главная: каталог курсов (G3).
      await expect(page.locator(".plan-title")).toHaveText("Главная");
      await expect(page.locator(".program-card-button").first()).toBeVisible();
      await expectNoHorizontalOverflow(page, "Главная");

      // Планы: «Мои тренировки» как вход в Builder.
      await openTab(page, "Планы");
      await expect(page.getByRole("heading", { name: "Мои тренировки" })).toBeVisible();
      await expectNoHorizontalOverflow(page, "Планы");

      // Журнал и Профиль: экран отрисован, без overflow.
      await openTab(page, "Журнал");
      await expect(page.locator("main, #root").first()).toBeVisible();
      await expectNoHorizontalOverflow(page, "Журнал");

      // Аналитика: переключатель «Тренировки | Программа», по умолчанию «Тренировки».
      await openTab(page, "Аналитика");
      await expect(page.getByRole("tab", { name: "Тренировки", selected: true })).toBeVisible();
      await expectNoHorizontalOverflow(page, "Аналитика");

      await openTab(page, "Профиль");
      await expect(page.locator("main, #root").first()).toBeVisible();
      await expectNoHorizontalOverflow(page, "Профиль");

      expect(consoleErrors).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
