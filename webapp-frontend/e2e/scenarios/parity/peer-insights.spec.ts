import { expect, test, type Page } from "@playwright/test";

import { noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";

// Crimpd parity — Peer insights (#276): «Сравнение с похожими» на детали теста.
// Сиды (scripts/e2e_seed.py, только e2e-БД):
//  * peer_cohort_female 994001 / peer_cohort_male 994002 — зритель (35 лет, 10 кг) + 24 синтетических
//    пользователя той же когорты в id-диапазонах 8_100_001.. / 8_200_001.. (значения 1..25 кг кроме 10):
//    когорта 25 человек -> процентиль 38, медиана 13 кг, следующий ориентир p50 = 13 кг.
//  * peer_insufficient 994011/994012 — один результат «Максимум подтягиваний», когорт на 20 нет.
//  * peer_empty 994021/994022 (320) и 994031/994032 (390) — без результатов; тест пишет результат (+retry).
// 320 px — светлая тема, 390 px — тёмная.
const THEMES = { 320: "light", 390: "dark" } as const;
const COHORT_VIEWER = { 320: { id: 994_001, label: "Женщины 30–39 лет" }, 390: { id: 994_002, label: "Мужчины 30–39 лет" } } as const;
const INSUFFICIENT_VIEWER = { 320: 994_011, 390: 994_012 } as const;
const EMPTY_VIEWER = { 320: 994_021, 390: 994_031 } as const;
const WEIGHTED = "Подтягивания с весом, кг";
const PULLUPS = "Максимум подтягиваний";
const INSUFFICIENT = "Пока мало данных для сравнения (нужно ≥20 человек)";

async function openTest(page: Page, name: string) {
  await page.getByTestId("home-tests-row").click();
  await page.getByTestId("test-card").filter({ hasText: name }).click();
  await expect(page.getByTestId("test-detail-title")).toHaveText(name);
}

for (const width of WIDTHS) {
  const theme = THEMES[width as 320 | 390];
  test.describe(`Peer insights @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 800 } });

    test("когорта из ≥20 человек: подпись, процентиль, медиана, следующий ориентир; в ответе только агрегаты", async ({ page }) => {
      const viewer = COHORT_VIEWER[width as 320 | 390];
      const bodies: string[] = [];
      page.on("response", async (response) => {
        if (response.url().includes("/peer-insights")) {
          bodies.push(await response.text());
        }
      });
      const { consoleErrors, apiFailures } = await openAppAs(page, viewer.id, { theme });
      await openTest(page, WEIGHTED);

      const card = page.getByTestId("peer-insights");
      await expect(page.getByTestId("peer-insights-title")).toHaveText("Сравнение с похожими");
      await expect(card.getByTestId("peer-insights-cohort")).toHaveText(`${viewer.label} · 20–49 человек`);
      await expect(card.getByTestId("peer-insights-percentile")).toHaveText("Лучше, чем у 38% похожих");
      await expect(card.getByTestId("peer-insights-median")).toHaveText("Медиана: 13 кг");
      await expect(card.getByTestId("peer-insights-next")).toHaveText("Следующий ориентир: 13 кг — лучше, чем у 50% похожих");
      await expect(card.getByTestId("peer-insights-bar-fill")).toHaveCSS("width", /\d/);
      await expect(card.getByTestId("peer-insights-insufficient")).toHaveCount(0);
      await expectNoHorizontalOverflow(page, "Тест: сравнение с похожими");

      // Утечки: в ответе нет чужих telegram id / имён и никаких списков.
      expect(bodies).toHaveLength(1);
      const body = JSON.parse(bodies[0]) as Record<string, unknown>;
      expect(Object.keys(body).sort()).toEqual(
        ["cohort", "median", "min_cohort_size", "next_target", "own_value", "percentile", "status", "unit"],
      );
      expect(bodies[0]).not.toMatch(/8_?[12]00\d{3}|peer81|peer82|telegram|user_id/);
      expect(Object.values(body).some((value) => Array.isArray(value))).toBe(false);
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("мало данных: точный текст вместо чисел", async ({ page }) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, INSUFFICIENT_VIEWER[width as 320 | 390], { theme });
      await openTest(page, PULLUPS);

      const card = page.getByTestId("peer-insights");
      await expect(card.getByTestId("peer-insights-insufficient")).toHaveText(INSUFFICIENT);
      await expect(card.getByTestId("peer-insights-percentile")).toHaveCount(0);
      await expect(card.getByTestId("peer-insights-median")).toHaveCount(0);
      await expect(card.getByTestId("peer-insights-bar")).toHaveCount(0);
      await expectNoHorizontalOverflow(page, "Тест: мало данных для сравнения");
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("нет результата: подсказка записать; после записи блок обновляется (мало данных)", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, EMPTY_VIEWER[width as 320 | 390] + testInfo.retry, { theme });
      await openTest(page, PULLUPS);

      const card = page.getByTestId("peer-insights");
      await expect(card.getByTestId("peer-insights-empty")).toHaveText("Запишите результат, чтобы сравнить себя с похожими.");
      const form = page.getByTestId("test-form");
      await form.getByLabel("Результат, повт.").fill("7");
      await form.getByRole("button", { name: "Записать результат" }).click();
      await expect(page.getByTestId("test-history-row")).toHaveCount(1);
      await expect(card.getByTestId("peer-insights-insufficient")).toHaveText(INSUFFICIENT);
      await expect(card.getByTestId("peer-insights-empty")).toHaveCount(0);
      await expectNoHorizontalOverflow(page, "Тест: после записи результата");
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
