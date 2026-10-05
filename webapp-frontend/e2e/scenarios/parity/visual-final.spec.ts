import { expect, test, type Page } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";

import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import type { TelegramTheme } from "../../fixtures/telegramMock";

// CRIMPD VISUAL — финальная волна (#286/#280, visual-final): нижней навигации нет на pushed-экранах
// (деталь, подборка, тесты, настройки, поиск, лист «Добавить в план»), «назад» доступна и возвращает навигацию;
// Главная: заголовок группы не наезжает на «Все ›»; «Итого» вместо TOTAL, честный счётчик «Показать все (+N)»,
// цвета категорий в легенде = цвета кольца; цветовая схема нативных контролов следует теме; шапка Workout Detail
// высокая; «Добавить в план» — нижний лист; склонение «тренировка/тренировки/тренировок».
// Сиды (только чтение): 997701 builder, 997702 home discovery, 997703 collections, 997706 settings, 997707 tests,
// 999301/999311 распределение аналитики, 910003 длинные имена категорий, 900003 профиль.
// Снимки: SHOTS=/tmp/visfinal-shots (локально, не коммитятся).
const THEMES: TelegramTheme[] = ["light", "dark"];
const DIST_BASE = { 320: 999_301, 390: 999_311 } as const;
const SHOTS = process.env.SHOTS;

async function snap(page: Page, width: number, theme: TelegramTheme, name: string) {
  if (!SHOTS) {
    return;
  }
  const dir = path.join(SHOTS, `${width}-${theme}`);
  fs.mkdirSync(dir, { recursive: true });
  await page.waitForTimeout(250);
  await page.screenshot({ path: path.join(dir, `${name}.png`), fullPage: true });
}

async function fresh(page: Page, id: number, theme: TelegramTheme) {
  await page.goto("about:blank");
  return openAppAs(page, id, { theme });
}

async function navVisible(page: Page): Promise<boolean> {
  return page.locator(".bottom-tabbar").isVisible();
}

for (const width of WIDTHS) {
  for (const theme of THEMES) {
    test.describe(`Visual final @${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: width === 320 ? 640 : 844 } });
      test.setTimeout(150_000);

      test("нижняя навигация скрыта на деталях и вторичных экранах, «назад» её возвращает", async ({ page }) => {
        const { consoleErrors } = await openAppAs(page, 997_701, { theme });
        await page.getByTestId("my-workouts").waitFor();
        expect(await navVisible(page), "Главная: навигация видна").toBe(true);

        // Workout Detail
        await page.getByTestId("my-workout-card").filter({ hasText: "Смешанная" }).click();
        await expect(page.getByTestId("workout-detail")).toBeVisible();
        expect(await navVisible(page), "Workout Detail: навигации нет").toBe(false);
        await expectNoHorizontalOverflow(page, "Workout Detail");
        const hero = (await page.getByTestId("workout-detail-hero").boundingBox())!;
        expect(hero.height, "шапка Workout Detail высокая (≥ 200 px)").toBeGreaterThanOrEqual(199);
        expect(hero.width).toBeGreaterThanOrEqual(width - 1); // на всю ширину
        await snap(page, width, theme, "workout_detail");

        // «Добавить в план» — нижний лист поверх приглушённого фона
        await page.getByRole("button", { name: "Добавить в план" }).click();
        const sheet = page.getByTestId("form-sheet");
        await expect(sheet).toBeVisible();
        expect(await navVisible(page), "лист: навигации нет").toBe(false);
        const box = (await sheet.boundingBox())!;
        const vh = page.viewportSize()!.height;
        expect(Math.round(box.y + box.height), "лист прижат к низу окна").toBe(vh);
        expect(box.y, "лист не на весь экран").toBeGreaterThan(0);
        await snap(page, width, theme, "add_to_plan_sheet");
        const free = page.getByRole("button", { name: "Свободный пул" });
        const freeBox = (await free.boundingBox())!;
        expect(freeBox.x, "«Свободный пул»: отступ слева от края листа").toBeGreaterThanOrEqual(box.x + 8);
        expect(freeBox.x + freeBox.width, "«Свободный пул» внутри листа").toBeLessThanOrEqual(box.x + box.width - 8);
        await expectNoHorizontalOverflow(page, "лист «Добавить в план»");
        await page.getByTestId("form-sheet-backdrop").click({ position: { x: 5, y: 5 } });
        await expect(page.getByTestId("workout-detail")).toBeVisible();

        // назад → навигация вернулась
        await page.getByTestId("workout-detail-back").click();
        await expect(page.getByTestId("my-workouts")).toBeVisible();
        expect(await navVisible(page), "после «назад» навигация вернулась").toBe(true);

        expect(consoleErrors.filter((e) => !/wake ?lock/i.test(e))).toEqual([]);
      });

      test("подборка, поиск, тесты (и деталь теста), настройки — без нижней навигации", async ({ page }) => {
        await openAppAs(page, 997_703, { theme });
        await page.getByTestId("collection-card").first().click();
        await expect(page.getByTestId("collection-screen")).toBeVisible();
        expect(await navVisible(page), "Подборка").toBe(false);
        await snap(page, width, theme, "collection");
        // eyebrow (автор) не слипается с заголовком
        const author = (await page.getByTestId("collection-author").boundingBox())!;
        const title = (await page.getByTestId("collection-title").boundingBox())!;
        expect(title.y - (author.y + author.height), "зазор между eyebrow и заголовком подборки").toBeGreaterThanOrEqual(4);
        await page.getByRole("button", { name: "← Назад" }).click();
        expect(await navVisible(page)).toBe(true);

        await fresh(page, 997_702, theme);
        await page.getByTestId("home-search-pill").click();
        await expect(page.getByTestId("search-screen")).toBeVisible();
        expect(await navVisible(page), "Поиск").toBe(false);

        await fresh(page, 997_707, theme);
        await page.getByTestId("home-tests-row").click();
        await expect(page.getByTestId("tests-screen")).toBeVisible();
        expect(await navVisible(page), "Тесты").toBe(false);
        await expect(page.getByTestId("test-card").first()).toBeVisible();
        await expectNoHorizontalOverflow(page, "Тесты");
        await snap(page, width, theme, "tests_hub");
        await page.getByTestId("test-card").first().click();
        await expect(page.getByTestId("test-detail")).toBeVisible();
        expect(await navVisible(page), "Деталь теста").toBe(false);
        // «назад» из детали → хаб, из хаба → Главная
        await page.getByRole("button", { name: "← Назад" }).first().click();
        await expect(page.getByTestId("tests-screen")).toBeVisible();
        await page.getByRole("button", { name: "← Назад" }).click();
        await expect(page.getByTestId("home-tests-row")).toBeVisible();
        expect(await navVisible(page), "после Тестов навигация вернулась").toBe(true);

        await fresh(page, 997_706, theme);
        await openTab(page, "Профиль");
        await page.getByTestId("profile-settings").click();
        await expect(page.getByTestId("settings-screen")).toBeVisible();
        expect(await navVisible(page), "Настройки").toBe(false);
        await expectNoHorizontalOverflow(page, "Настройки");
        // нативные контролы (select/date) — по теме Telegram, не ОС
        expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme), "color-scheme").toBe(theme);
        await snap(page, width, theme, "settings");
        await page.getByTestId("settings-cancel").click();
        expect(await navVisible(page)).toBe(true);
      });

      test("Главная: заголовок группы не наезжает на «Все ›»", async ({ page }) => {
        for (const id of [997_702, 910_003]) {
          await fresh(page, id, theme);
          await expect(page.getByTestId("program-category").first()).toBeVisible();
          await snap(page, width, theme, `home_${id}`);
          const groups = page.getByTestId("program-category");
          const count = await groups.count();
          for (let i = 0; i < count; i++) {
            const group = groups.nth(i);
            const all = group.getByTestId("program-category-all");
            if ((await all.count()) === 0) {
              continue;
            }
            const t = (await group.getByTestId("program-category-title").boundingBox())!;
            const a = (await all.boundingBox())!;
            expect(t.x + t.width, `заголовок группы ${i} левее «Все ›»`).toBeLessThanOrEqual(a.x + 0.5);
            expect(a.x + a.width, "«Все ›» в окне").toBeLessThanOrEqual(width);
          }
          await expectNoHorizontalOverflow(page, "Главная");
        }
      });

      test("Аналитика: «Итого», честный счётчик, цвета легенды = кольцо; склонение в Профиле", async ({ page }, testInfo) => {
        await openAppAs(page, DIST_BASE[width] + testInfo.retry, { theme });
        await openTab(page, "Аналитика");
        await expect(page.getByTestId("analytics-metrics")).toBeVisible();
        await snap(page, width, theme, "analytics");
        const summary = page.getByTestId("analytics-summary");
        await summary.scrollIntoViewIfNeeded();
        await expect(summary.getByTestId("summary-total").locator("th")).toHaveText("Итого");
        await expect(summary).not.toContainText("TOTAL");

        // «Показать все (+N)»: N = сколько строк реально добавится
        const rows = summary.locator("tbody tr:not(.analytics-summary-total)");
        const before = await rows.count();
        const label = (await page.getByTestId("summary-show-all").textContent()) ?? "";
        const claimed = Number(/\+(\d+)/.exec(label)?.[1]);
        await page.getByTestId("summary-show-all").click();
        expect((await rows.count()) - before, "счётчик «+N» совпадает с добавленными строками").toBe(claimed);

        // категории окрашены по-разному; цвет легенды = цвет сегмента кольца
        const legend = await page.locator(".analytics-legend-swatch").evaluateAll((els) => els
          .filter((el) => el.closest(".analytics-legend"))
          .map((el) => getComputedStyle(el).backgroundColor));
        const donut = await page.getByTestId("donut-inner-segment").evaluateAll((els) => els.map((el) => getComputedStyle(el).fill));
        expect(legend.length).toBeGreaterThanOrEqual(2);
        expect(new Set(legend).size, "у категорий разные цвета").toBe(legend.length);
        expect(donut.sort()).toEqual([...legend].sort());
        await expectNoHorizontalOverflow(page, "Аналитика");

        // Профиль: подпись счётчика согласована с числом
        await fresh(page, 900_003, theme);
        await openTab(page, "Профиль");
        const tile = page.locator(".stat-tile").first();
        const n = Number((await tile.locator(".stat-value").textContent()) ?? "0");
        const noun = ((await tile.locator(".stat-label").textContent()) ?? "").trim();
        const mod100 = n % 100;
        const expected = mod100 >= 11 && mod100 <= 14 ? "Тренировок" : n % 10 === 1 ? "Тренировка" : n % 10 >= 2 && n % 10 <= 4 ? "Тренировки" : "Тренировок";
        expect(noun).toBe(expected);
      });
    });
  }
}
