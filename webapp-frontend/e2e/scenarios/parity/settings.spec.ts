import { expect, test, type Page } from "@playwright/test";

import { noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";

// Crimpd parity — Settings (#268): Профиль → ⚙️ «Настройки» (единицы, тема, таймер, подписка, данные).
// Тесты мутируют настройки, поэтому у каждого свой посеянный `ready`-пользователь (+retry):
// 996001/996011 (единицы), +2 (тема), +4 (отмена). Вес 75 кг, рост 180 см (_QUESTIONNAIRE_DEFAULTS).
const BASE = { 320: 996_001, 390: 996_011 } as const;
const THEMES = { 320: "light", 390: "dark" } as const;
const LIGHT_BG = "rgb(255, 255, 255)";
const DARK_BG = "rgb(23, 33, 43)";

const bodyBg = (page: Page) => page.evaluate(() => getComputedStyle(document.body).backgroundColor);

async function openSettings(page: Page) {
  await openTab(page, "Профиль");
  await page.getByTestId("profile-settings").click();
  await expect(page.getByTestId("settings-screen")).toBeVisible();
}

for (const width of WIDTHS) {
  const theme = THEMES[width as 320 | 390];
  const base = BASE[width as 320 | 390];
  test.describe(`Settings @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 800 } });

    test("секции экрана; единицы фунты/дюймы → профиль показывает пересчёт, хранение метрическое", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, base + testInfo.retry, { theme });
      await openTab(page, "Профиль");
      await expect(page.getByTestId("profile-weight")).toHaveText("Вес: 75 кг");
      await expect(page.getByTestId("profile-height")).toHaveText("Рост: 180 см");

      await page.getByTestId("profile-settings").click();
      const screen = page.getByTestId("settings-screen");
      for (const title of ["Профиль", "Единицы", "Оформление", "Таймер", "Подписка", "Данные"]) {
        await expect(screen.locator(".section-title", { hasText: title }).first()).toBeVisible();
      }
      await expect(screen.getByText("Часовой пояс").first()).toBeVisible();
      await expect(page.getByTestId("settings-export")).toBeVisible();
      await expect(page.getByTestId("settings-oferta")).toBeVisible();
      await expect(page.getByRole("button", { name: "Как в Telegram" })).toHaveAttribute("aria-pressed", "true");
      await expectNoHorizontalOverflow(page, "Настройки");

      await page.getByTestId("settings-weight-unit").getByRole("button", { name: "фунты" }).click();
      await page.getByTestId("settings-height-unit").getByRole("button", { name: "дюймы" }).click();
      await expect(page.getByRole("spinbutton", { name: "Вес" })).toHaveValue("165.3");
      await expect(page.getByRole("spinbutton", { name: "Рост" })).toHaveValue("70.9");
      await page.getByTestId("settings-save").click();

      await expect(page.getByTestId("profile-weight")).toHaveText("Вес: 165.3 фунт.");
      await expect(page.getByTestId("profile-height")).toHaveText("Рост: 70.9 дюйм.");
      // Хранение метрическое: API по-прежнему отдаёт кг/см.
      const profile = await page.evaluate(async () => {
        const raw = (window as unknown as { Telegram: { WebApp: { initData: string } } }).Telegram.WebApp.initData;
        const r = await fetch("/api/profile", { headers: { "X-Telegram-Init-Data": raw } });
        return r.json();
      });
      expect(Number(profile.weight_kg)).toBeCloseTo(75, 0);
      expect(profile.height_cm).toBe(180);

      // Применено «везде»: после перезагрузки настройки подтягиваются с сервера.
      await page.reload();
      await openTab(page, "Профиль");
      await expect(page.getByTestId("profile-height")).toHaveText("Рост: 70.9 дюйм.");
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("тема-override: ничего не меняется до «Сохранить», затем применяется и переживает перезагрузку", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, base + 2 + testInfo.retry, { theme });
      const initialBg = theme === "dark" ? DARK_BG : LIGHT_BG;
      const target = theme === "dark" ? "Светлая" : "Тёмная";
      const targetBg = theme === "dark" ? LIGHT_BG : DARK_BG;
      await expect.poll(() => bodyBg(page)).toBe(initialBg);

      await openSettings(page);
      await page.getByTestId("settings-theme").getByRole("button", { name: target }).click();
      expect(await bodyBg(page)).toBe(initialBg); // черновик ещё не применён
      await page.getByTestId("settings-save").click();
      await expect.poll(() => bodyBg(page)).toBe(targetBg);

      await page.reload();
      await expect.poll(() => bodyBg(page)).toBe(targetBg);

      // Возврат на «Как в Telegram» снимает override.
      await openSettings(page);
      await page.getByTestId("settings-theme").getByRole("button", { name: "Как в Telegram" }).click();
      await page.getByTestId("settings-save").click();
      await expect.poll(() => bodyBg(page)).toBe(initialBg);
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("«Отмена» отбрасывает правки: единицы, тема и вес остаются прежними", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, base + 4 + testInfo.retry, { theme });
      const initialBg = theme === "dark" ? DARK_BG : LIGHT_BG;
      await openSettings(page);
      await page.getByTestId("settings-weight-unit").getByRole("button", { name: "фунты" }).click();
      await page.getByTestId("settings-theme").getByRole("button", { name: theme === "dark" ? "Светлая" : "Тёмная" }).click();
      await page.getByRole("spinbutton", { name: "Вес" }).fill("99");
      await page.getByTestId("settings-cancel").click();

      await expect(page.getByTestId("profile-weight")).toHaveText("Вес: 75 кг");
      expect(await bodyBg(page)).toBe(initialBg);

      // Повторное открытие — снова сохранённые значения, не черновик.
      await page.getByTestId("profile-settings").click();
      await expect(page.getByTestId("settings-weight-unit").getByRole("button", { name: "кг" })).toHaveAttribute("aria-pressed", "true");
      await expect(page.getByRole("spinbutton", { name: "Вес" })).toHaveValue("75");
      await expect(page.getByRole("button", { name: "Как в Telegram" })).toHaveAttribute("aria-pressed", "true");
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
