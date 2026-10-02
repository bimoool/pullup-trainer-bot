import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import type { TelegramTheme } from "../../fixtures/telegramMock";

// CRIMPD VISUAL (#280): контракт общей мобильной оболочки — нижняя навигация из 5 вкладок
// с активным состоянием, заголовок экрана и заголовки секций на каждой вкладке, sticky-поиск
// на Главной, отсутствие горизонтального overflow, различимые поверхности «страница/карточка».
// Seed: scripts/e2e_seed.py home_discovery — 9994xx, только чтение; по пользователю на
// ширину × тему и + retry.
const TABS = ["Главная", "Планы", "Журнал", "Аналитика", "Профиль"] as const;
const SCREEN_TITLES: Record<(typeof TABS)[number], string> = {
  "Главная": "Главная", "Планы": "Планы", "Журнал": "Журнал", "Аналитика": "Аналитика", "Профиль": "Профиль",
};
const USERS: Record<number, Record<TelegramTheme, number>> = {
  320: { light: 999_401, dark: 999_411 },
  390: { light: 999_421, dark: 999_431 },
};

async function surfaceColors(page: Page) {
  return page.evaluate(() => {
    const body = getComputedStyle(document.body).backgroundColor;
    const card = document.querySelector(".profile-card, .history-card, .home-workout-card, .home-tests-row");
    return { body, card: card ? getComputedStyle(card).backgroundColor : null };
  });
}

for (const width of WIDTHS) {
  for (const theme of ["light", "dark"] as TelegramTheme[]) {
    test.describe(`Visual shell @${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: 740 } });
      test.setTimeout(90_000);

      test("нижняя навигация: 5 вкладок, активная помечена, внутри окна; заголовки экранов; без overflow", async ({ page }, testInfo) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, USERS[width][theme] + testInfo.retry, { theme });
        const nav = page.locator(".bottom-tabbar");
        await expect(nav).toBeVisible();
        await expect(nav.getByRole("button")).toHaveCount(5);
        await expectNoHorizontalOverflow(page, "Главная");

        for (const label of TABS) {
          const tab = nav.getByRole("button", { name: label, exact: true });
          await expect(tab).toBeVisible();
          // иконка + подпись в каждой вкладке
          await expect(tab.locator("svg")).toHaveCount(1);
          await tab.click();
          await expect(tab).toHaveAttribute("aria-current", "page");
          await expect(nav.locator('[aria-current="page"]')).toHaveCount(1);
          await expect(page.locator(".plan-title").filter({ hasText: SCREEN_TITLES[label] }).first()).toBeVisible();
          await page.waitForTimeout(400);
          await expectNoHorizontalOverflow(page, label);

          const box = (await nav.boundingBox())!;
          expect(box.x).toBeGreaterThanOrEqual(0);
          expect(box.x + box.width).toBeLessThanOrEqual(width);
          expect(Math.round(box.y + box.height), "навигация прижата к низу окна").toBe(740);
        }
        expect(consoleErrors).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("Главная: заголовки секций, горизонтальные ряды, sticky-поиск остаётся при прокрутке", async ({ page }, testInfo) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, USERS[width][theme] + testInfo.retry, { theme });
        await page.getByTestId("my-workouts").waitFor();
        await page.getByTestId("program-category-title").first().waitFor();
        await expect(page.locator(".section-title").first()).toBeVisible();
        expect(await page.locator(".section-title").count(), "заголовки секций").toBeGreaterThanOrEqual(3);
        await expect(page.getByTestId("program-category-title").first()).toBeVisible();
        await expect(page.locator(".section-title", { hasText: "Мои тренировки" })).toBeVisible();

        // горизонтальный ряд: прокручиваемый контейнер, следующая карточка выглядывает
        const row = page.getByTestId("program-row").first();
        const geometry = await row.evaluate((el) => ({
          scrollable: el.scrollWidth >= el.clientWidth,
          overflowX: getComputedStyle(el).overflowX,
        }));
        expect(geometry.overflowX).toBe("auto");
        expect(geometry.scrollable).toBe(true);

        const pill = page.getByTestId("home-search-pill");
        await expect(pill).toBeInViewport();
        await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
        await page.waitForTimeout(250);
        expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(300);
        await expect(pill).toBeInViewport();
        const top = (await page.getByTestId("home-header").boundingBox())!.y;
        expect(top, "шапка прилипает к верху").toBeLessThanOrEqual(2);
        await expectNoHorizontalOverflow(page, "Главная после прокрутки");
        expect(consoleErrors).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("поверхности: фон страницы и карточки различаются; Workout Detail — 4 действия без overflow", async ({ page }, testInfo) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, USERS[width][theme] + testInfo.retry, { theme });
        await page.getByTestId("my-workouts").waitFor();
        const colors = await surfaceColors(page);
        expect(colors.card, "на Главной есть карточка").not.toBeNull();
        expect(colors.card).not.toBe(colors.body);

        await page.getByTestId("my-workout-card").first().click();
        await expect(page.getByTestId("workout-detail")).toBeVisible();
        const actions = page.locator(".workout-detail-actions .workout-detail-action");
        await expect(actions).toHaveCount(4);
        for (let i = 0; i < 4; i++) {
          const box = (await actions.nth(i).boundingBox())!;
          expect(box.x).toBeGreaterThanOrEqual(0);
          expect(box.x + box.width).toBeLessThanOrEqual(width);
        }
        await expect(page.locator(".section-title", { hasText: "Упражнения" })).toBeVisible();
        await expectNoHorizontalOverflow(page, "Workout Detail");
        expect(consoleErrors).toEqual([]);
        expect(apiFailures).toEqual([]);
      });
    });
  }
}
