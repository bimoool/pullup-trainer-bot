import { expect, test, type Page } from "@playwright/test";

import { noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";

// Crimpd parity — Body metrics (#270): Профиль → «Вес» → история (SVG-тренд, список, добавить/изменить/удалить).
// Сид `body_metrics`: вес 75 кг «сейчас» + 76.5 (14 дн. назад) + 78 (30 дн. назад), рост 180 см.
// Тесты мутируют историю, поэтому у каждого свой пользователь (+retry): 999201/999211 (экран), +2 (правка/удаление).
const BASE = { 320: 999_201, 390: 999_211 } as const;
const THEMES = { 320: "light", 390: "dark" } as const;

async function openWeightHistory(page: Page) {
  await openTab(page, "Профиль");
  await page.getByTestId("profile-weight").click();
  await expect(page.getByTestId("body-metrics-screen")).toBeVisible();
}

const rowValues = (page: Page) => page.getByTestId("body-metrics-row-value").allTextContents();

for (const width of WIDTHS) {
  const theme = THEMES[width as 320 | 390];
  const base = BASE[width as 320 | 390];
  test.describe(`Body metrics @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 800 } });

    test("Профиль → «Вес»: тренд, список от новых к старым, текущее значение; назад в профиль", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, base + testInfo.retry, { theme });
      await openTab(page, "Профиль");
      await expect(page.getByTestId("profile-weight")).toHaveText("Вес: 75 кг");

      await page.getByTestId("profile-weight").click();
      await expect(page.getByRole("heading", { name: "Вес" }).or(page.locator(".plan-title", { hasText: "Вес" }))).toBeVisible();
      await expect(page.getByTestId("body-metrics-current")).toHaveText("Сейчас: 75 кг");
      await expect(page.getByTestId("body-metrics-trend")).toBeVisible();
      await expect(page.getByTestId("body-metrics-trend").locator("circle")).toHaveCount(3);
      await expect(page.getByTestId("body-metrics-delta")).toHaveText("К предыдущему замеру: -1.5 кг");
      expect(await rowValues(page)).toEqual(["75 кг", "76.5 кг", "78 кг"]);
      await expect(page.getByTestId("body-metrics-add")).toBeVisible();
      await expectNoHorizontalOverflow(page, "История веса");

      await page.getByTestId("body-metrics-back").click();
      await expect(page.getByTestId("profile-weight")).toBeVisible();

      // Рост тоже имеет историю (одна запись → графика нет, удалять единственный замер нельзя на бэкенде).
      await page.getByTestId("profile-height").click();
      await expect(page.getByTestId("body-metrics-current")).toHaveText("Сейчас: 180 см");
      await expect(page.getByTestId("body-metrics-trend-empty")).toBeVisible();
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("добавить, изменить и удалить замер: профиль зеркалит последний, удаление — с подтверждением", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, base + 2 + testInfo.retry, { theme });
      await openWeightHistory(page);

      // Добавить замер (сегодня) — становится текущим.
      await page.getByTestId("body-metrics-add").click();
      await page.getByRole("spinbutton", { name: "Вес замера" }).fill("74.2");
      await page.getByTestId("body-metrics-save").click();
      await expect(page.getByTestId("body-metrics-current")).toHaveText("Сейчас: 74.2 кг");
      await expect(page.getByTestId("body-metrics-row")).toHaveCount(4);
      expect((await rowValues(page))[0]).toBe("74.2 кг");
      await expectNoHorizontalOverflow(page, "История веса после добавления");

      // Изменить последний замер.
      await page.getByTestId("body-metrics-edit").first().click();
      await expect(page.getByRole("spinbutton", { name: "Вес замера" })).toHaveValue("74.2");
      await page.getByRole("spinbutton", { name: "Вес замера" }).fill("74");
      await page.getByTestId("body-metrics-save").click();
      await expect(page.getByTestId("body-metrics-current")).toHaveText("Сейчас: 74 кг");

      // Отмена подтверждения — ничего не удалено.
      page.once("dialog", (dialog) => void dialog.dismiss());
      await page.getByTestId("body-metrics-delete").first().click();
      await expect(page.getByTestId("body-metrics-row")).toHaveCount(4);

      // Подтверждение — откат к предыдущему замеру (75 кг).
      page.once("dialog", (dialog) => void dialog.accept());
      await page.getByTestId("body-metrics-delete").first().click();
      await expect(page.getByTestId("body-metrics-row")).toHaveCount(3);
      await expect(page.getByTestId("body-metrics-current")).toHaveText("Сейчас: 75 кг");

      await page.getByTestId("body-metrics-back").click();
      await expect(page.getByTestId("profile-weight")).toHaveText("Вес: 75 кг");
      // Зеркало в User видно и из API (его читают GTO/WSF/лидерборд).
      const profile = await page.evaluate(async () => {
        const raw = (window as unknown as { Telegram: { WebApp: { initData: string } } }).Telegram.WebApp.initData;
        const r = await fetch("/api/profile", { headers: { "X-Telegram-Init-Data": raw } });
        return r.json();
      });
      expect(Number(profile.weight_kg)).toBe(75);
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
