import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import type { TelegramTheme } from "../../fixtures/telegramMock";

// CRIMPD VISUAL, tier 2 (#280): Журнал (компактная карточка + метка типа), Профиль (grouped list),
// Аналитика (подчёркнутые табы, цвета легенды), Планы (цвет программы, чипы дней), promo-баннеры Главной.
// Все сценарии только читают seed (--read-only): 940001 Главная, 910002 Журнал, 900003 Профиль,
// 910003 Аналитика, 900013 Планы.
const USERS = { home: 940_001, journal: 910_002, profile: 900_003, analytics: 910_003, plans: 900_013 } as const;

async function open(page: Page, id: number, theme: TelegramTheme, tab?: string) {
  const result = await openAppAs(page, id, { theme });
  if (tab) {
    await openTab(page, tab);
  }
  return result;
}

for (const width of WIDTHS) {
  for (const theme of ["light", "dark"] as TelegramTheme[]) {
    test.describe(`Visual screens @${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: 740 } });
      test.setTimeout(90_000);

      test("Журнал: карточка из 2 строк с цветной меткой типа, заголовок дня, календарь без overflow", async ({ page }) => {
        const { consoleErrors, apiFailures } = await open(page, USERS.journal, theme, "Журнал");
        await expect(page.locator(".journal-card").first()).toBeVisible();
        // компактность проверяем на записи из одного блока (многоблочные переносят блоки в строку меты)
        const card = page.locator(".journal-card").filter({ hasNot: page.locator(".journal-block + .journal-block") }).first();
        await expect(card).toBeVisible();
        await expect(page.locator(".journal-day-header").first()).toBeVisible();
        await expect(page.locator(".journal-week-header").first()).toBeVisible();

        const body = card.locator(".journal-card-body");
        await expect(body.locator("> p"), "ровно две строки: название и мета").toHaveCount(2);
        await expect(body.locator(".journal-card-title")).toBeVisible();
        await expect(body.locator(".journal-card-meta")).toBeVisible();
        const marker = card.getByTestId("journal-kind-marker");
        await expect(marker).toBeVisible();
        const markerColor = await marker.evaluate((el) => getComputedStyle(el).backgroundColor);
        expect(markerColor).not.toBe("rgba(0, 0, 0, 0)");
        const kind = await card.getAttribute("data-kind");
        expect(["plan", "freeform", "logged", "elective", "backdated"]).toContain(kind);
        const box = (await card.boundingBox())!;
        expect(box.height, "компактная карточка одного блока").toBeLessThanOrEqual(84);
        await expectNoHorizontalOverflow(page, "Журнал: лента");

        await page.locator(".journal-month-label").click();
        await expect(page.locator(".journal-calendar-grid")).toBeVisible();
        await expectNoHorizontalOverflow(page, "Журнал: календарь");
        expect(consoleErrors).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("Профиль: grouped list со строками-иконками и шевронами", async ({ page }) => {
        const { consoleErrors, apiFailures } = await open(page, USERS.profile, theme, "Профиль");
        await expect(page.getByTestId("profile-weight")).toHaveText("Вес: 75 кг");
        expect(await page.locator(".profile-group").count(), "группы").toBeGreaterThanOrEqual(3);
        const links = page.locator(".profile-row-link");
        expect(await links.count()).toBeGreaterThanOrEqual(5);
        for (const link of await links.all()) {
          await expect(link.locator(".profile-row-icon svg")).toHaveCount(1);
          await expect(link.locator(".profile-row-chevron")).toHaveCount(1);
        }
        await expect(page.locator(".stat-tile")).toHaveCount(3);
        await expect(page.getByTestId("profile-tests").getByTestId("test-card")).toHaveCount(3);
        await expectNoHorizontalOverflow(page, "Профиль");
        expect(consoleErrors).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("Аналитика: табы с подчёркиванием, метрика в шапке, цвета легенды = цвета групп Главной", async ({ page }) => {
        const { consoleErrors, apiFailures } = await open(page, USERS.analytics, theme, "Аналитика");
        const card = page.getByTestId("analytics-metrics");
        await expect(card).toBeVisible();
        const range = card.getByRole("tablist", { name: "Период" });
        await expect(range.getByRole("tab")).toHaveText(["1 мес", "3 мес", "Свой"]);
        const active = range.getByRole("tab", { selected: true });
        const underline = await active.evaluate((el) => {
          const style = getComputedStyle(el);
          return { width: parseFloat(style.borderBottomWidth), color: style.borderBottomColor, radius: style.borderTopLeftRadius };
        });
        expect(underline.width).toBeGreaterThanOrEqual(2);
        expect(underline.color).not.toBe("rgba(0, 0, 0, 0)");
        expect(underline.radius).toBe("0px");
        // метрика — в шапке карточки, над периодом
        const header = card.locator(".analytics-metric-header");
        await expect(header.getByRole("tablist", { name: "Метрика" }).getByRole("tab")).toHaveText(["Тренировки", "Минуты"]);
        await expect(page.getByRole("tablist", { name: "Раздел аналитики" }).getByRole("tab", { selected: true }))
          .toHaveText("Тренировки");

        // первая категория легенды окрашена цветом первой группы Главной (--vp-cat-0)
        const swatch = page.getByTestId("analytics-legend-item").first().locator(".analytics-legend-swatch");
        await expect(swatch).toBeVisible();
        const colors = await page.evaluate(() => {
          const probe = document.createElement("div");
          probe.style.background = "var(--vp-cat-0)";
          document.body.appendChild(probe);
          const home = getComputedStyle(probe).backgroundColor;
          probe.remove();
          return { home, swatch: getComputedStyle(document.querySelector(".analytics-legend-swatch")!).backgroundColor };
        });
        expect(colors.swatch).toBe(colors.home);
        await expect(page.locator(".analytics-summary-swatch").first()).toBeVisible();
        await expectNoHorizontalOverflow(page, "Аналитика");
        expect(consoleErrors).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("Планы: карточка курса цветом программы, чипы дней", async ({ page }) => {
        const { consoleErrors, apiFailures } = await open(page, USERS.plans, theme, "Планы");
        const course = page.getByTestId("plans-now-inclusion").first();
        await expect(course).toBeVisible();
        await expect.poll(() => course.getAttribute("style"), "цвет категории подгружен").toContain("--vp-cat-");
        const colors = await course.evaluate((el) => ({
          bg: getComputedStyle(el).backgroundColor,
          card: getComputedStyle(el.closest(".profile-card")!).backgroundColor,
        }));
        expect(colors.bg).not.toBe(colors.card);
        const chip = page.locator(".plan-week-current .plan-week-day-group > .block-subtitle").first();
        if (await chip.count()) {
          const style = await chip.evaluate((el) => ({ display: getComputedStyle(el).display, radius: parseFloat(getComputedStyle(el).borderTopLeftRadius) }));
          expect(style.display).toBe("inline-block");
          expect(style.radius).toBeGreaterThan(8);
        }
        await expectNoHorizontalOverflow(page, "Планы");
        expect(consoleErrors).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("Главная: promo-баннеры с уникальными именами, без дублей «Создать тренировку»", async ({ page }) => {
        const { consoleErrors, apiFailures } = await open(page, USERS.home, theme);
        await page.getByTestId("my-workouts").waitFor();
        const names = ["Баннер: открыть план дня", "Баннер: внести активность", "Баннер: собрать свой комплекс"];
        for (const name of names) {
          await expect(page.getByRole("button", { name, exact: true })).toHaveCount(1);
        }
        // имена кнопок действий остаются уникальными для строгих селекторов
        await expect(page.getByRole("button", { name: "Создать", exact: true })).toHaveCount(1);
        await expect(page.getByRole("button", { name: /Создать тренировку/ })).toHaveCount(0);
        await expect(page.getByRole("button", { name: "Записать" })).toHaveCount(0);
        const banner = page.getByTestId("home-promo-create");
        await banner.scrollIntoViewIfNeeded();
        const box = (await banner.boundingBox())!;
        expect(box.x).toBeGreaterThanOrEqual(0);
        expect(box.x + box.width).toBeLessThanOrEqual(width);
        await expectNoHorizontalOverflow(page, "Главная с баннерами");

        await banner.click();
        await expect(page.getByTestId("home-search-pill"), "ушли с Главной в редактор").toHaveCount(0);
        expect(consoleErrors).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("Главная: баннер «внести активность» открывает Журнал со шторкой записи", async ({ page }) => {
        await open(page, USERS.home, theme);
        await page.getByTestId("my-workouts").waitFor();
        await page.getByRole("button", { name: "Баннер: внести активность" }).click();
        await expect(page.locator(".journal-title-row")).toBeVisible();
        await expect(page.getByTestId("log-option-workout")).toBeVisible();
      });

      test("все вкладки без горизонтального overflow", async ({ page }) => {
        await open(page, USERS.home, theme);
        await page.getByTestId("my-workouts").waitFor();
        for (const tab of ["Главная", "Планы", "Журнал", "Аналитика", "Профиль"]) {
          await openTab(page, tab);
          await page.waitForTimeout(500);
          await expectNoHorizontalOverflow(page, tab);
        }
      });
    });
  }
}
