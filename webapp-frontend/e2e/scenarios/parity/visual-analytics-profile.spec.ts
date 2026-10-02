import { expect, test, type Locator, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import type { TelegramTheme } from "../../fixtures/telegramMock";

// CRIMPD VISUAL, tier 4 / C (#286): Аналитика — единая шапка, KPI одной строкой, «по типам» раньше «по неделям»,
// легенда цветами палитры, сводка без нулей, многоточие вместо разрыва слов; Профиль — шапка-идентичность, крупные
// вес/рост, тесты плоским списком с бейджем, без эмодзи в кнопках.
// Сиды (только чтение): 910003 Аналитика (длинные имена категорий), 999301/999311 распределение (3 категории с данными
// + нули каталога), 900003 Профиль (мужской, вес 75 кг, рост 180 см, три теста).
const DIST_BASE = { 320: 999_301, 390: 999_311 } as const;
const EMOJI = /\p{Extended_Pictographic}/u;

async function box(locator: Locator) {
  const result = await locator.boundingBox();
  expect(result, "элемент отрисован").not.toBeNull();
  return result!;
}

async function openAnalytics(page: Page, id: number, theme: TelegramTheme) {
  const result = await openAppAs(page, id, { theme, firstName: "Кирилл" });
  await openTab(page, "Аналитика");
  await expect(page.getByTestId("analytics-metrics")).toBeVisible();
  return result;
}

for (const width of WIDTHS) {
  for (const theme of ["light", "dark"] as TelegramTheme[]) {
    test.describe(`Visual analytics+profile @${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: 800 } });
      test.setTimeout(90_000);

      test("Аналитика: одна шапка, KPI-строка, «по типам» выше «по неделям», легенда разными цветами палитры", async ({ page }, testInfo) => {
        const { consoleErrors, apiFailures } = await openAnalytics(page, DIST_BASE[width as 320 | 390] + testInfo.retry, theme);

        // единая шапка: список метрики слева и табы периода справа на одной строке; отдельного ряда «Метрика» нет
        const strip = page.locator(".analytics-header-strip");
        await expect(strip).toHaveCount(1);
        const select = strip.getByRole("combobox", { name: "Метрика" });
        const range = strip.getByRole("tablist", { name: "Период" });
        await expect(select).toBeVisible();
        await expect(range).toBeVisible();
        await expect(page.getByRole("tablist", { name: "Метрика" })).toHaveCount(0);
        const selectBox = await box(select);
        const rangeBox = await box(range);
        expect(selectBox.x + selectBox.width, "список метрики левее табов периода").toBeLessThanOrEqual(rangeBox.x + 1);
        expect(Math.abs(selectBox.y + selectBox.height / 2 - (rangeBox.y + rangeBox.height / 2)), "одна строка").toBeLessThan(14);
        await expect(select.locator("option")).toHaveText(["Тренировки", "Минуты"]);

        // два KPI — одна компактная строка
        const kpi = page.getByTestId("analytics-kpi-row");
        await expect(kpi.locator(".analytics-stat")).toHaveCount(2);
        expect((await box(kpi)).height, "компактная строка KPI").toBeLessThanOrEqual(84);

        // порядок: шапка → KPI → «по типам» → «по неделям» → сводка
        const ys = [strip, kpi, page.getByTestId("analytics-distribution"), page.getByTestId("analytics-weeks"), page.getByTestId("analytics-summary")];
        const tops: number[] = [];
        for (const locator of ys) {
          tops.push((await box(locator)).y);
        }
        expect(tops, "порядок блоков").toEqual([...tops].sort((a, b) => a - b));

        // легенда: цвета палитры --vp-cat-*, разные у разных категорий; «Другая активность» — нейтральный
        const legend = page.getByTestId("analytics-legend-item");
        await expect(legend).toHaveCount(3);
        const swatches = await legend.locator(".analytics-legend-swatch").evaluateAll((els) => els.map((el) => getComputedStyle(el).backgroundColor));
        const palette = await page.evaluate(() => [0, 1, 2, 3, 4, 5].map((i) => {
          const probe = document.createElement("div");
          probe.style.background = `var(--vp-cat-${i})`;
          document.body.appendChild(probe);
          const color = getComputedStyle(probe).backgroundColor;
          probe.remove();
          return color;
        }));
        expect(new Set(swatches).size, "цвета легенды различны").toBe(3);
        expect(palette).toContain(swatches[0]);
        expect(palette).toContain(swatches[1]);
        expect(palette).not.toContain(swatches[2]);
        // кольцо окрашено теми же цветами, что легенда
        const ringFills = await page.getByTestId("donut-inner-segment").evaluateAll((els) => els.map((el) => getComputedStyle(el).fill));
        expect(ringFills).toEqual(swatches);

        await expect(page.locator("[data-testid=analytics-metrics] button").filter({ hasText: EMOJI })).toHaveCount(0);
        await expectNoHorizontalOverflow(page, "Аналитика: шапка и блоки");
        expect(consoleErrors).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("Аналитика: сводка без нулевых строк + «Показать все», длинные названия — многоточие без разрыва слов", async ({ page }, testInfo) => {
        const { consoleErrors, apiFailures } = await openAnalytics(page, DIST_BASE[width as 320 | 390] + testInfo.retry, theme);
        const summary = page.getByTestId("analytics-summary");
        await summary.scrollIntoViewIfNeeded();
        // по умолчанию: только категории с данными (pull, core, «Другая активность»)
        await expect(summary.getByTestId("summary-category")).toHaveCount(3);
        await expect(summary.getByTestId("summary-category").filter({ hasText: "e2e_dist_legs" })).toHaveCount(0);
        const showAll = page.getByTestId("summary-show-all");
        await expect(showAll).toContainText("Показать все");
        await showAll.click();
        expect(await summary.getByTestId("summary-category").count()).toBeGreaterThan(3);
        await expect(summary.getByTestId("summary-category").filter({ hasText: "e2e_dist_legs" })).toHaveCount(1);
        await expect(showAll).toContainText("Скрыть пустые");

        // первая колонка и легенда: одна строка + многоточие, без переноса внутри слова
        const cellStyles = await summary.locator("tbody th").evaluateAll((els) => els.map((el) => {
          const style = getComputedStyle(el);
          return { whiteSpace: style.whiteSpace, textOverflow: style.textOverflow, overflowWrap: style.overflowWrap, height: el.getBoundingClientRect().height };
        }));
        for (const style of cellStyles) {
          expect(style.whiteSpace).toBe("nowrap");
          expect(style.textOverflow).toBe("ellipsis");
          expect(style.overflowWrap).toBe("normal");
          expect(style.height, "строка таблицы в одну строку").toBeLessThan(40);
        }
        const legendStyle = await page.locator(".analytics-legend-name").first().evaluate((el) => {
          const style = getComputedStyle(el);
          return { whiteSpace: style.whiteSpace, textOverflow: style.textOverflow };
        });
        expect(legendStyle).toEqual({ whiteSpace: "nowrap", textOverflow: "ellipsis" });
        await expectNoHorizontalOverflow(page, "Аналитика: сводка, все строки");
        expect(consoleErrors).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("Профиль: шапка-идентичность, крупные вес/рост, тесты плоским списком, SVG вместо эмодзи", async ({ page }) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, 900_003, { theme, firstName: "Кирилл" });
        await openTab(page, "Профиль");

        const identity = page.getByTestId("profile-identity");
        await expect(identity).toBeVisible();
        await expect(page.getByTestId("profile-name")).toHaveText("Кирилл");
        await expect(page.getByTestId("profile-identity-meta")).toHaveText(/^мужской · \d+ (год|года|лет)$/);
        await expect(identity.locator(".profile-avatar")).toHaveText("К");

        // порядок: идентичность → плитки статистики → личные данные → тесты
        const identityBox = await box(identity);
        const statsBox = await box(page.locator(".stat-grid"));
        const weightBox = await box(page.getByTestId("profile-weight"));
        const testsBox = await box(page.getByTestId("profile-tests"));
        expect(identityBox.y).toBeLessThan(statsBox.y);
        expect(statsBox.y).toBeLessThan(weightBox.y);
        expect(weightBox.y).toBeLessThan(testsBox.y);

        // вес/рост — крупные акцентные числа со стрелкой, textContent прежний
        const weight = page.getByTestId("profile-weight");
        const height = page.getByTestId("profile-height");
        await expect(weight).toHaveText("Вес: 75 кг");
        await expect(height).toHaveText("Рост: 180 см");
        for (const metric of [weight, height]) {
          await expect(metric.locator(".profile-row-chevron")).toHaveCount(1);
          const number = metric.locator(".profile-metric-number");
          const style = await number.evaluate((el) => {
            const probe = document.createElement("span");
            probe.style.color = "var(--vp-accent)";
            document.body.appendChild(probe);
            const accent = getComputedStyle(probe).color;
            probe.remove();
            return { size: parseFloat(getComputedStyle(el).fontSize), color: getComputedStyle(el).color, accent };
          });
          expect(style.size).toBeGreaterThanOrEqual(24);
          expect(style.color).toBe(style.accent);
        }

        // тесты — плоский список с разделителями: бейдж (::before), название, последний результат, шеврон (::after)
        const cards = page.getByTestId("profile-tests").getByTestId("test-card");
        await expect(cards).toHaveCount(3);
        for (let i = 0; i < 3; i += 1) {
          const card = cards.nth(i);
          await expect(card.getByTestId("test-card-name")).toBeVisible();
          await expect(card.getByTestId("test-card-last")).toBeVisible();
          const parts = await card.evaluate((el) => ({
            badge: getComputedStyle(el, "::before").content,
            badgeWidth: getComputedStyle(el, "::before").width,
            chevron: getComputedStyle(el, "::after").content,
            radius: getComputedStyle(el).borderTopLeftRadius,
            divider: parseFloat(getComputedStyle(el).borderTopWidth),
          }));
          expect(parts.badge).not.toBe("none");
          expect(parts.badgeWidth).toBe("32px");
          expect(parts.chevron).not.toBe("none");
          expect(parts.radius, "плоская строка, не вложенная плитка").toBe("0px");
          if (i > 0) {
            expect(parts.divider).toBeGreaterThanOrEqual(1);
          }
        }

        // кнопки Профиля без эмодзи; иконки — SVG
        const buttons = page.locator("button");
        for (const text of await buttons.allTextContents()) {
          expect(text, `эмодзи в кнопке «${text}»`).not.toMatch(EMOJI);
        }
        for (const label of await buttons.evaluateAll((els) => els.map((el) => el.getAttribute("aria-label") ?? ""))) {
          expect(label).not.toMatch(EMOJI);
        }
        await expect(page.getByTestId("profile-settings").locator("svg")).toHaveCount(1);
        await expect(page.getByRole("button", { name: "Настройки" })).toHaveCount(1);
        for (const name of [/^Подписка/, /^Изменить/, /^Справка/, /^Мои резины/, /^Ачивок/]) {
          await expect(page.getByRole("button", { name })).toHaveCount(1);
        }
        await expectNoHorizontalOverflow(page, "Профиль: идентичность и метрики");
        expect(consoleErrors).toEqual([]);
        expect(apiFailures).toEqual([]);
      });
    });
  }
}
