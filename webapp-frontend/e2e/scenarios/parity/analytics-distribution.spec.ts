import { expect, test, type Page } from "@playwright/test";

import { noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, openTab, selectMetric, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";

// Crimpd parity — Analytics distribution (#274): Аналитика → «По типам» (SVG-кольцо + легенда) и «Сводка».
// Сид `analytics_distribution` (только чтение; 999301/999311 + retry): за 1 мес «Хват» 2 тр./60 мин
// (вертикальная 1/40, горизонтальная 1/20), ОФП 1/10, «Ноги» 0/0, «Другая активность» 1/30; итого 4 / 100.
// За 3 мес ОФП 2/70, итого 5 / 160. Тренировка атомарна (#308): все числа целые, подписи человеческие.
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
      await expect(legend.filter({ hasText: "Хват" })).toContainText("2 ·");
      await expect(legend.filter({ hasText: "Другая активность" })).toContainText("1 ·");
      await expect(legend.filter({ hasText: "Ноги" })).toHaveCount(0);

      // Два кольца: внутреннее — 3 категории; внешнее — vertical, horizontal, остаток pull-нет, core, другая.
      await expect(page.getByTestId("analytics-donut")).toBeVisible();
      await expect(page.getByTestId("donut-inner-segment")).toHaveCount(3);
      await expect(page.getByTestId("donut-outer-segment")).toHaveCount(4);
      // Цвета легенды — из палитры проекта `--vp-cat-*` (цвет категории по имени, #286) и различимы между собой.
      const swatches = await legend.locator(".analytics-legend-swatch").evaluateAll((els) => els.map((el) => getComputedStyle(el).backgroundColor));
      const palette = await page.evaluate(() => [0, 1, 2, 3, 4, 5].map((i) => {
        const probe = document.createElement("div");
        probe.style.background = `var(--vp-cat-${i})`;
        document.body.appendChild(probe);
        const color = getComputedStyle(probe).backgroundColor;
        probe.remove();
        return color;
      }));
      const [pull, core, other] = swatches; // порядок легенды: pull, core, «Другая активность» (нейтральный)
      expect(palette).toContain(pull);
      expect(palette).toContain(core);
      expect(new Set(swatches).size, "три разных цвета").toBe(3);
      expect(palette).not.toContain(other);
      await expectNoHorizontalOverflow(page, "Аналитика: распределение");

      // Метрика «Минуты» перерисовывает кольцо: хват 60, ОФП 10, другая 30.
      await selectMetric(page, "Минуты");
      await expect(legend.filter({ hasText: "Хват" })).toContainText("1 ч");
      await expect(legend.filter({ hasText: "Другая активность" })).toContainText("30 мин");
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("сводка: категории и подкатегории, нули для каталога, «Итого»; 3 мес меняет значения", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, base + testInfo.retry, { theme });
      await openTab(page, "Аналитика");

      const summary = page.getByTestId("analytics-summary");
      await summary.scrollIntoViewIfNeeded();
      await expect(summary.locator("thead")).toContainText("Тренировки");
      await expect(summary.locator("thead")).toContainText("Минуты");
      expect(await cells(row(page, "Хват"))).toEqual(["Хват", "2", "60"]);
      expect(await cells(row(page, "Общая физическая подготовка"))).toEqual(["Общая физическая подготовка", "1", "10"]);
      // нулевые строки каталога скрыты по умолчанию и раскрываются кнопкой «Показать все»
      await expect(row(page, "Ноги")).toHaveCount(0);
      await page.getByTestId("summary-show-all").click();
      expect(await cells(row(page, "Ноги"))).toEqual(["Ноги", "0", "0"]);
      await page.getByTestId("summary-show-all").click();
      await expect(row(page, "Ноги")).toHaveCount(0);
      expect(await cells(row(page, "Другая активность"))).toEqual(["Другая активность", "1", "30"]);
      const subs = page.locator('[data-testid="summary-subcategory"][data-category="Хват"]');
      expect(await subs.evaluateAll((rows) => rows.map((r) => [...r.querySelectorAll("th, td")].map((c) => c.textContent?.trim())))).toEqual([
        ["Вертикальная", "1", "40"], ["Горизонтальная", "1", "20"],
      ]);
      const total = page.getByTestId("summary-total");
      expect(await cells(total)).toEqual(["Итого", "4", "100"]);
      // «Другая активность» — последняя категория.
      await expect(page.getByTestId("summary-category").last()).toHaveAttribute("data-category", "Другая активность");
      await expectNoHorizontalOverflow(page, "Аналитика: сводка");

      await page.getByRole("tab", { name: "3 мес" }).click();
      await expect.poll(async () => cells(total)).toEqual(["Итого", "5", "160"]);
      expect(await cells(row(page, "Общая физическая подготовка"))).toEqual(["Общая физическая подготовка", "2", "70"]);
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
