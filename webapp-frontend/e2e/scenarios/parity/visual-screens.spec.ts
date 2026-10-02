import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import type { TelegramTheme } from "../../fixtures/telegramMock";

// CRIMPD VISUAL, tier 2 (#280): Журнал (компактная карточка + метка типа), Профиль (grouped list),
// Аналитика (подчёркнутые табы, цвета легенды), Планы (цвет программы, чипы дней), promo-баннеры Главной.
// Все сценарии только читают seed (--read-only): 940001 Главная, 997708 Журнал (свой сид: 910002 мутирует journal-v2.spec.ts), 900003 Профиль,
// 910003 Аналитика, 900013 Планы.
const USERS = { home: 940_001, journal: 997_708, profile: 900_003, analytics: 910_003, plans: 900_013 } as const;

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

      test("Журнал: карточка «бейдж + название» и подписанная сетка из 3 показателей, цветная метка типа, заголовок дня, календарь без overflow", async ({ page }) => {
        const { consoleErrors, apiFailures } = await open(page, USERS.journal, theme, "Журнал");
        await expect(page.locator(".journal-card").first()).toBeVisible();
        const card = page.locator(".journal-card").first();
        await expect(page.locator(".journal-day-header").first()).toBeVisible();
        await expect(page.locator(".journal-week-header").first()).toBeVisible();

        // Референс Crimpd (#286): строка «бейдж типа + название (+ время)», ниже сетка из 3 подписанных колонок.
        const body = card.locator(".journal-card-body");
        await expect(body.locator("> *"), "две части: строка заголовка и сетка показателей").toHaveCount(2);
        const title = body.locator(".journal-card-title");
        await expect(title).toBeVisible();
        await expect(title.getByTestId("journal-kind-badge")).toBeVisible();
        await expect(title.locator(".journal-card-name")).not.toBeEmpty();
        const grid = body.getByTestId("journal-stat-grid");
        await expect(grid).toBeVisible();
        const stats = grid.locator(".journal-stat");
        await expect(stats, "3 показателя").toHaveCount(3);
        for (const stat of await stats.all()) {
          await expect(stat.locator(".journal-stat-label")).not.toBeEmpty();
          await expect(stat.locator(".journal-stat-value")).not.toBeEmpty();
        }
        await expect(grid.locator(".journal-stat-label").last()).toHaveText("Усилие");
        const columns = await grid.evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(" ").length);
        expect(columns, "3 колонки").toBe(3);
        const xs = await Promise.all((await stats.all()).map(async (stat) => (await stat.boundingBox())!.x));
        expect(xs[0] < xs[1] && xs[1] < xs[2], "показатели в один ряд слева направо").toBe(true);
        const marker = card.getByTestId("journal-kind-marker");
        await expect(marker).toBeVisible();
        const markerColor = await marker.evaluate((el) => getComputedStyle(el).backgroundColor);
        expect(markerColor).not.toBe("rgba(0, 0, 0, 0)");
        // цвет усилия на карточке читаем как текст: контраст ≥ 4.5:1 с фоном карточки (шкала effortScale 1–4; 5 — системный «destructive»)
        const contrasts = await page.evaluate(() => {
          const toRgb = (css: string) => {
            const ctx = document.createElement("canvas").getContext("2d")!;
            ctx.fillStyle = "#000"; ctx.fillStyle = css; ctx.fillRect(0, 0, 1, 1);
            return Array.from(ctx.getImageData(0, 0, 1, 1).data).slice(0, 3);
          };
          const lum = ([r, g, b]: number[]) => {
            const [R, G, B] = [r, g, b].map((v) => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; });
            return 0.2126 * R + 0.7152 * G + 0.0722 * B;
          };
          return Array.from(document.querySelectorAll<HTMLElement>('.journal-card .journal-effort[data-effort]'))
            .filter((el) => Number(el.dataset.effort) <= 4)
            .map((el) => {
              const fg = lum(toRgb(getComputedStyle(el).color));
              const bg = lum(toRgb(getComputedStyle(el.closest(".journal-card")!).backgroundColor));
              return (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
            });
        });
        for (const ratio of contrasts) {
          expect(ratio, "контраст цвета усилия на карточке").toBeGreaterThanOrEqual(4.5);
        }
        const kind = await card.getAttribute("data-kind");
        expect(["plan", "freeform", "logged", "elective", "backdated"]).toContain(kind);
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
        expect(await links.count()).toBeGreaterThanOrEqual(4);
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

      test("Аналитика: единая шапка (метрика-список + табы с подчёркиванием), цвета легенды из палитры --vp-cat-*", async ({ page }) => {
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
        // метрика — выпадающий список в той же шапке, что и период
        const header = card.getByTestId("analytics-header");
        await expect(header.getByRole("combobox", { name: "Метрика" }).locator("option")).toHaveText(["Тренировки", "Минуты"]);
        // iOS зумит страницу при фокусе на поле < 16px: селект метрики не должен быть мельче
        const metricFont = await header.getByRole("combobox", { name: "Метрика" }).evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
        expect(metricFont, "селект метрики ≥ 16px (без iOS-зума)").toBeGreaterThanOrEqual(16);
        await expect(page.getByRole("tablist", { name: "Раздел аналитики" }).getByRole("tab", { selected: true }))
          .toHaveText("Тренировки");

        // цвет легенды — один из --vp-cat-0..5 (цвет категории по имени, #286)
        const swatch = page.getByTestId("analytics-legend-item").first().locator(".analytics-legend-swatch");
        await expect(swatch).toBeVisible();
        const colors = await page.evaluate(() => {
          const probe = document.createElement("div");
          const palette = [0, 1, 2, 3, 4, 5].map((i) => {
            probe.style.background = `var(--vp-cat-${i})`;
            document.body.appendChild(probe);
            return getComputedStyle(probe).backgroundColor;
          });
          probe.remove();
          return { palette, swatch: getComputedStyle(document.querySelector(".analytics-legend-swatch")!).backgroundColor };
        });
        expect(colors.palette).toContain(colors.swatch);
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
