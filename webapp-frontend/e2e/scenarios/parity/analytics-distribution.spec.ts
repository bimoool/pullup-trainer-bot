import { expect, test, type Page } from "@playwright/test";

import { noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";

// Crimpd parity — Analytics distribution (#274): Аналитика → «По типам» (SVG-кольцо + легенда) и «Сводка».
// Сид `analytics_distribution` (только чтение; 999301/999311 + retry): за 1 мес pull 1.5 тр./50 мин
// (vertical 1/40, horizontal 0.5/10), core 0.5/10, legs 0/0, «Другая активность» 1/30; итого 3 / 90.
// За 3 мес core 1.5/70, итого 4 / 150.
const BASE = { 320: 999_301, 390: 999_311 } as const;
const THEMES = { 320: "light", 390: "dark" } as const;

const row = (page: Page, category: string) =>
  page.locator(`[data-testid="summary-category"][data-category="${category}"]`);
const cells = async (locator: ReturnType<typeof row>) => (await locator.locator("th, td").allTextContents()).map((t) => t.trim());

for (const width of WIDTHS) {
  const theme = THEMES[width as 320 | 390];
  const base = BASE[width as 320 | 390];
  test.describe(`Analytics distribution @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 800 } });

    test("кольцо и легенда: категории, подкатегории, «Другая активность»; без overflow", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, base + testInfo.retry, { theme });
      await openTab(page, "Аналитика");

      const block = page.getByTestId("analytics-distribution");
      await block.scrollIntoViewIfNeeded();
      await expect(block).toContainText("По типам");
      const legend = page.getByTestId("analytics-legend-item");
      await expect(legend).toHaveCount(3); // категории с ненулевым значением: pull, core, «Другая активность»
      await expect(legend.filter({ hasText: "e2e_dist_pull" })).toContainText("1.5");
      await expect(legend.filter({ hasText: "Другая активность" })).toContainText("1 ·");
      await expect(legend.filter({ hasText: "e2e_dist_legs" })).toHaveCount(0);

      // Два кольца: внутреннее — 3 категории; внешнее — vertical, horizontal, остаток pull-нет, core, другая.
      await expect(page.getByTestId("analytics-donut")).toBeVisible();
      await expect(page.getByTestId("donut-inner-segment")).toHaveCount(3);
      await expect(page.getByTestId("donut-outer-segment")).toHaveCount(4);
      // Цвета легенды берутся из палитры проекта: первая категория — синий ряд аналитики.
      const swatch = await legend.first().locator(".analytics-legend-swatch").evaluate((el) => getComputedStyle(el).backgroundColor);
      expect(swatch).toBe("rgb(42, 120, 214)");
      await expectNoHorizontalOverflow(page, "Аналитика: распределение");

      // Метрика «Минуты» перерисовывает кольцо: pull 50, core 10, другая 30.
      await page.getByRole("tab", { name: "Минуты" }).click();
      await expect(legend.filter({ hasText: "e2e_dist_pull" })).toContainText("50 мин");
      await expect(legend.filter({ hasText: "Другая активность" })).toContainText("30 мин");
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("сводка: категории и подкатегории, нули для каталога, TOTAL; 3 мес меняет значения", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, base + testInfo.retry, { theme });
      await openTab(page, "Аналитика");

      const summary = page.getByTestId("analytics-summary");
      await summary.scrollIntoViewIfNeeded();
      await expect(summary.locator("thead")).toContainText("Тренировки");
      await expect(summary.locator("thead")).toContainText("Минуты");
      expect(await cells(row(page, "e2e_dist_pull"))).toEqual(["e2e_dist_pull", "1.5", "50"]);
      expect(await cells(row(page, "e2e_dist_core"))).toEqual(["e2e_dist_core", "0.5", "10"]);
      expect(await cells(row(page, "e2e_dist_legs"))).toEqual(["e2e_dist_legs", "0", "0"]); // нули для каталога
      expect(await cells(row(page, "Другая активность"))).toEqual(["Другая активность", "1", "30"]);
      const subs = page.locator('[data-testid="summary-subcategory"][data-category="e2e_dist_pull"]');
      expect(await subs.evaluateAll((rows) => rows.map((r) => [...r.querySelectorAll("th, td")].map((c) => c.textContent?.trim())))).toEqual([
        ["horizontal", "0.5", "10"], ["vertical", "1", "40"],
      ]);
      const total = page.getByTestId("summary-total");
      expect(await cells(total)).toEqual(["TOTAL", "3", "90"]);
      // «Другая активность» — последняя категория.
      await expect(page.getByTestId("summary-category").last()).toHaveAttribute("data-category", "Другая активность");
      await expectNoHorizontalOverflow(page, "Аналитика: сводка");

      await page.getByRole("tab", { name: "3 мес" }).click();
      await expect.poll(async () => cells(total)).toEqual(["TOTAL", "4", "150"]);
      expect(await cells(row(page, "e2e_dist_core"))).toEqual(["e2e_dist_core", "1.5", "70"]);
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
