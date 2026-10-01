import { expect, test, type Page } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";
import type { TelegramTheme } from "../fixtures/telegramMock";

// Критичная мобильная раскладка (issue #244). Гоняется проектами mobile-320/
// 375/390 (см. playwright.config.ts). Только чтение: посеянный `ready`
// (scripts/e2e_seed.py ready 900003) — данные не меняются, повторный прогон безопасен.
const TELEGRAM_ID = 900_003;

const TABS = ["Главная", "Планы", "Журнал", "Аналитика", "Профиль"];

// Страница не должна получать горизонтальный скролл.
async function expectNoHorizontalOverflow(page: Page, where: string) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth, `горизонтальный overflow на «${where}»`).toBeLessThanOrEqual(clientWidth);
}

// Подпись вкладки не обрезана: текст целиком внутри окна и не шире своего бокса.
async function expectLabelNotClipped(page: Page, label: string) {
  const text = page.getByText(label, { exact: true }).last();
  await expect(text).toBeVisible();
  const box = await text.boundingBox();
  const vw = page.viewportSize()!.width;
  expect(box, `нет бокса у «${label}»`).not.toBeNull();
  expect(box!.x, `«${label}» левее экрана`).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width, `«${label}» правее экрана`).toBeLessThanOrEqual(vw);
  const clipped = await text.evaluate((el) => {
    // Любой предок с overflow != visible, чей бокс уже текста, обрежет подпись.
    const r = el.getBoundingClientRect();
    if (el.scrollWidth > el.clientWidth + 1) return true;
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (s.overflowX === "visible") continue;
      const pr = p.getBoundingClientRect();
      if (r.left < pr.left - 1 || r.right > pr.right + 1) return true;
    }
    return false;
  });
  expect(clipped, `подпись «${label}» обрезана`).toBe(false);
}

for (const theme of ["light", "dark"] as TelegramTheme[]) {
  test(`нижняя навигация и экраны без обрезки и overflow — тема ${theme}`, async ({ page }) => {
    const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID, { theme });

    const nav = page.locator(".bottom-tabbar");
    await expect(nav).toBeVisible();
    await expectNoHorizontalOverflow(page, "Главная (старт)");

    for (const label of TABS) {
      const tab = nav.getByRole("button", { name: label });
      await expect(tab).toBeVisible();
      await expectLabelNotClipped(page, label);

      await tab.click();
      // Каждая вкладка должна отрисовать основное содержимое помимо навигации.
      await expect(page.locator("main, #root").first()).toBeVisible();
      await expectNoHorizontalOverflow(page, label);

      // Навигация остаётся целиком в окне и не уезжает вбок.
      const navBox = await nav.boundingBox();
      const vw = page.viewportSize()!.width;
      expect(navBox!.x).toBeGreaterThanOrEqual(0);
      expect(navBox!.x + navBox!.width).toBeLessThanOrEqual(vw);
    }

    expect(consoleErrors).toEqual([]);
    expect(apiFailures).toEqual([]);
  });
}
