import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import type { TelegramTheme } from "../../fixtures/telegramMock";

// CRIMPD VISUAL tier 4 (#286 A): анатомия Главной и Workout Detail.
//  - ряды: первая карточка на x = 16, следующая выглядывает (баг scroll-snap без scroll-padding);
//  - порядок секций как в эталоне, «Избранное» скрыто, пока пусто, бейдж категории = глиф;
//  - Workout Detail: hero-обложка, название ≤ 2 строк, 4 тональных действия в ряд (и на 320),
//    нижняя навигация скрыта на детали и видна на вкладках.
// Seed: home_discovery 9995xx (те же пользователи, что visual-shell; только чтение).
const USERS: Record<number, Record<TelegramTheme, number>> = {
  320: { light: 999_501, dark: 999_511 },
  390: { light: 999_521, dark: 999_531 },
};

async function yOf(page: Page, selector: string): Promise<number | null> {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    return el ? el.getBoundingClientRect().top + window.scrollY : null;
  }, selector);
}

for (const width of WIDTHS) {
  for (const theme of ["light", "dark"] as TelegramTheme[]) {
    test.describe(`Visual home/detail @${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: 760 } });
      test.setTimeout(90_000);

      test("Главная: первая карточка ряда на x=16, вторая выглядывает; бейджи-глифы; заголовок не занимает место", async ({ page }, testInfo) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, USERS[width][theme] + testInfo.retry, { theme });
        await page.getByTestId("program-category-title").first().waitFor();

        const rows = await page.getByTestId("program-row").evaluateAll((els) => els.map((row) => {
          const cards = [...row.querySelectorAll(".home-program-card")].map((c) => c.getBoundingClientRect());
          return { scrollLeft: (row as HTMLElement).scrollLeft, count: cards.length, first: cards[0], second: cards[1] };
        }));
        const multi = rows.filter((row) => row.count >= 2);
        expect(multi.length, "есть ряд минимум с двумя карточками").toBeGreaterThan(0);
        for (const row of rows) {
          expect(row.scrollLeft, "ряд не прокручен при загрузке").toBe(0);
          expect(Math.round(row.first.x), "первая карточка ряда на инсете 16px").toBe(16);
        }
        for (const row of multi) {
          expect(row.second.x, "вторая карточка начинается внутри окна").toBeLessThan(width - 24);
          expect(row.second.x + row.second.width, "вторая карточка выходит за край (выглядывает)").toBeGreaterThan(width);
        }

        // бейдж категории — глиф (svg), а не пустая точка
        const badges = page.locator(".home-group-badge");
        expect(await badges.count()).toBeGreaterThan(0);
        for (const badge of await badges.all()) {
          await expect(badge.locator("svg")).toHaveCount(1);
        }

        // «Главная»: заголовок для AT есть, но визуально строки нет — поиск у самого верха
        await expect(page.getByRole("heading", { name: "Главная", level: 1 })).toHaveCount(1);
        const title = (await page.locator(".plan-title").boundingBox())!;
        expect(title.height).toBeLessThanOrEqual(2);
        const pill = (await page.getByTestId("home-header").boundingBox())!;
        expect(pill.y, "строка поиска — у самого верха").toBeLessThanOrEqual(12);
        const firstGroup = (await page.getByTestId("program-category").first().boundingBox())!;
        expect(firstGroup.y, "категории сразу под поиском").toBeLessThan(130);
        await expectNoHorizontalOverflow(page, "Главная: ряды");
        expect(consoleErrors).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("Главная: порядок секций как в эталоне, «Избранное» скрыто, пока пусто", async ({ page }, testInfo) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, USERS[width][theme] + testInfo.retry, { theme });
        await page.getByTestId("my-workouts").waitFor();
        await page.getByTestId("program-category-title").first().waitFor();
        await page.getByTestId("home-tests-row").waitFor();
        await expect(page.getByTestId("collections-row")).toBeVisible();

        const order: [string, string][] = [
          ["категории", '[data-testid="program-category"]'],
          ["подборки", '[data-testid="collections-row"]'],
          ["баннер: сборка", '[data-testid="home-promo-create"]'],
          ["мои тренировки", '[data-testid="my-workouts"]'],
          ["баннер: запись", '[data-testid="home-promo-log"]'],
          ["баннер: план дня", '[data-testid="home-promo-plan"]'],
          ["тесты", '[data-testid="home-tests-row"]'],
        ];
        const ys: number[] = [];
        for (const [name, selector] of order) {
          const y = await yOf(page, selector);
          expect(y, `секция «${name}» на месте`).not.toBeNull();
          ys.push(y!);
        }
        const firstCategory = await yOf(page, '[data-testid="program-category"]');
        const lastCategory = await page.evaluate(() => {
          const all = document.querySelectorAll('[data-testid="program-category"]');
          return all[all.length - 1].getBoundingClientRect().top + window.scrollY;
        });
        expect(firstCategory!).toBeLessThan(lastCategory + 1);
        expect(lastCategory, "все категории выше «Подборок»").toBeLessThan(ys[1]);
        for (let i = 1; i < ys.length; i++) {
          expect(ys[i], `«${order[i][0]}» ниже «${order[i - 1][0]}»`).toBeGreaterThan(ys[i - 1] - 1);
        }

        // Пустое «Избранное»: ни заголовка, ни ряда; допустима только тихая подсказка без заголовка
        await expect(page.getByTestId("favorites-row")).toHaveCount(0);
        await expect(page.locator(".section-title", { hasText: "Избранное" })).toHaveCount(0);
        const hint = await yOf(page, '[data-testid="favorites-hint"]');
        if (hint !== null) {
          expect(hint, "подсказка — после «Мои тренировки», перед баннером плана").toBeGreaterThan(ys[3]);
          expect(hint).toBeLessThan(ys[5]);
        }
        await expectNoHorizontalOverflow(page, "Главная: порядок секций");
        expect(consoleErrors).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("Workout Detail: hero, название ≤ 2 строк, 4 действия в ряд, навигация скрыта на детали и видна на вкладках", async ({ page }, testInfo) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, USERS[width][theme] + testInfo.retry, { theme });
        const nav = page.locator(".bottom-tabbar");
        await expect(nav).toBeVisible();
        await page.getByTestId("my-workout-card").filter({ hasText: "Очень длинная" }).click();
        await expect(page.getByTestId("workout-detail")).toBeVisible();
        await expect(nav, "на детали нижней навигации нет").toBeHidden();

        const hero = (await page.getByTestId("workout-detail-hero").boundingBox())!;
        expect(hero.height).toBeGreaterThanOrEqual(199);
        expect(hero.height).toBeLessThanOrEqual(262);
        expect(Math.round(hero.x)).toBe(0);
        expect(Math.round(hero.width)).toBe(width);
        await expect(page.getByTestId("workout-detail-hero").locator(".wd-hero-badge svg")).toHaveCount(1);

        const title = page.getByTestId("workout-detail-title");
        const titleGeometry = await title.evaluate((el) => {
          const style = getComputedStyle(el);
          return { fontSize: parseFloat(style.fontSize), lineHeight: parseFloat(style.lineHeight), height: el.getBoundingClientRect().height };
        });
        expect(titleGeometry.fontSize).toBeGreaterThanOrEqual(22);
        expect(titleGeometry.fontSize).toBeLessThanOrEqual(24);
        expect(titleGeometry.height, "название — не более двух строк").toBeLessThanOrEqual(titleGeometry.lineHeight * 2 + 1);

        const pill = page.getByTestId("workout-detail-meta");
        await expect(pill).toBeVisible();

        // 4 действия: одна строка, внутри окна, подпись не обрезана, круг 44px, тональные (без карточки вокруг)
        const actions = page.locator(".workout-detail-actions .workout-detail-action");
        await expect(actions).toHaveCount(4);
        const boxes = [];
        for (let i = 0; i < 4; i++) {
          const box = (await actions.nth(i).boundingBox())!;
          boxes.push(box);
          expect(box.x).toBeGreaterThanOrEqual(0);
          expect(box.x + box.width).toBeLessThanOrEqual(width);
          const label = await actions.nth(i).locator(".workout-detail-action-label").evaluate((el) => ({
            clipped: el.scrollWidth > el.clientWidth + 1, lines: Math.round(el.getBoundingClientRect().height / parseFloat(getComputedStyle(el).lineHeight)),
          }));
          expect(label.clipped, `подпись действия ${i + 1} не обрезана`).toBe(false);
          expect(label.lines).toBeLessThanOrEqual(2);
          const icon = (await actions.nth(i).locator(".workout-detail-action-icon").boundingBox())!;
          expect(Math.round(icon.width)).toBe(44);
          expect(Math.round(icon.height)).toBe(44);
        }
        for (let i = 1; i < 4; i++) {
          expect(Math.abs(boxes[i].y - boxes[0].y), "4 действия в один ряд").toBeLessThanOrEqual(2);
          expect(boxes[i].x, "колонки слева направо без наложения").toBeGreaterThanOrEqual(boxes[i - 1].x + boxes[i - 1].width - 1);
        }
        const wrapperBg = await page.locator(".workout-detail-actions").evaluate((el) => getComputedStyle(el).backgroundColor);
        expect(wrapperBg, "действия не в карточке").toBe("rgba(0, 0, 0, 0)");
        await expect(page.getByRole("button", { name: "Изменить", exact: true })).toBeVisible();
        await expectNoHorizontalOverflow(page, "Workout Detail hero");

        // «назад» из шапки возвращает на Главную, где навигация снова видна; вкладки работают
        await page.getByRole("button", { name: "Назад", exact: true }).click();
        await expect(page.getByTestId("my-workouts")).toBeVisible();
        await expect(nav).toBeVisible();
        for (const tab of ["Планы", "Журнал", "Главная"]) {
          await nav.getByRole("button", { name: tab, exact: true }).click();
          await expect(nav).toBeVisible();
        }
        expect(consoleErrors).toEqual([]);
        expect(apiFailures).toEqual([]);
      });
    });
  }
}
