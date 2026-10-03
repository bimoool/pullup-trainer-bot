import { expect, test, type Page } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";

import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import { pressTelegramBackButton, type TelegramTheme } from "../../fixtures/telegramMock";

// CRIMPD VISUAL (#286 G): «Настройки» — сгруппированные секции-строки без эмодзи, тёмные поверхности и
// color-scheme по теме; «Тесты» — карточки (бейдж, название, последний результат, шеврон) и честный «назад»
// (Telegram BackButton и «← Назад»): Главная → Тесты → деталь → список → Главная; Профиль → Настройки / тест → Профиль.
// Сиды (только чтение): 997706 ready (настройки), 997707 tests_hub. Снимки: SHOTS=/tmp/vset-shots.
const THEMES: TelegramTheme[] = ["light", "dark"];
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

/** Яркость 0..1 из computed `rgb()/rgba()`. */
function luminance(css: string): number {
  const m = css.match(/[\d.]+/g)!.map(Number);
  return (0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]) / 255;
}

const EMOJI = /\p{Extended_Pictographic}/u;
const bg = (page: Page, selector: string) =>
  page.locator(selector).first().evaluate((el) => getComputedStyle(el).backgroundColor);

for (const width of WIDTHS) {
  for (const theme of THEMES) {
    test.describe(`Visual settings/tests @${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: width === 320 ? 640 : 844 } });
      test.setTimeout(120_000);

      test("Настройки: группы-секции со строками, без эмодзи, тёмные поверхности, color-scheme по теме", async ({ page }) => {
        const { consoleErrors } = await openAppAs(page, 997_706, { theme });
        await openTab(page, "Профиль");
        await page.getByTestId("profile-settings").click();
        const screen = page.getByTestId("settings-screen");
        await expect(screen).toBeVisible();
        await snap(page, width, theme, "settings");

        // сгруппированные секции: подпись над карточкой, карточек не меньше, чем подписей
        const titles = screen.locator(".settings-group-title");
        for (const title of ["Профиль", "Единицы", "Оформление", "Таймер", "Подписка", "Данные"]) {
          await expect(titles.filter({ hasText: title }).first()).toBeVisible();
        }
        expect(await screen.locator(".settings-group").count()).toBeGreaterThanOrEqual(await titles.count());
        // строки профиля: 4 строки с иконкой-SVG и разделителями
        const profileRows = page.getByTestId("settings-profile-group").locator(".settings-row");
        await expect(profileRows).toHaveCount(4);
        await expect(profileRows.locator("svg")).toHaveCount(4);
        const second = await profileRows.nth(1).evaluate((el) => getComputedStyle(el).borderTopWidth);
        expect(second, "разделитель между строками").not.toBe("0px");
        // нативные контролы есть и доступны по имени
        await expect(page.getByRole("combobox", { name: "Пол" })).toBeVisible();
        await expect(page.getByRole("combobox", { name: "Часовой пояс" })).toBeVisible();
        await expect(page.getByRole("textbox", { name: "Вес" })).toBeVisible();

        // никаких эмодзи-иконок в строках/заголовках; иконки — SVG
        expect(EMOJI.test((await screen.textContent()) ?? ""), "эмодзи в тексте настроек").toBe(false);
        for (const id of ["settings-oferta", "settings-export"]) {
          await expect(page.getByTestId(id).locator("svg").first()).toBeVisible();
        }

        // поверхности и color-scheme по теме
        const scheme = await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme);
        expect(scheme, "color-scheme").toBe(theme);
        const select = await page.getByRole("combobox", { name: "Пол" }).evaluate((el) => getComputedStyle(el).colorScheme);
        expect(select, "color-scheme нативного select").toBe(theme);
        const card = luminance(await bg(page, ".settings-screen .profile-card"));
        const body = luminance(await page.evaluate(() => getComputedStyle(document.body).backgroundColor));
        if (theme === "dark") {
          expect(card, "тёмная карточка").toBeLessThan(0.3);
          expect(body, "тёмная страница").toBeLessThan(0.3);
        } else {
          expect(card, "светлая карточка").toBeGreaterThan(0.8);
          expect(body, "светлая страница").toBeGreaterThan(0.8);
        }
        await expectNoHorizontalOverflow(page, "Настройки");
        expect(consoleErrors.filter((e) => !/wake ?lock/i.test(e))).toEqual([]);
      });

      test("Настройки: «Отмена» и Telegram BackButton возвращают в Профиль", async ({ page }) => {
        await openAppAs(page, 997_706, { theme, backButton: true });
        await openTab(page, "Профиль");
        await page.getByTestId("profile-settings").click();
        await expect(page.getByTestId("settings-screen")).toBeVisible();
        await page.getByTestId("settings-cancel").click();
        await expect(page.getByTestId("profile-settings")).toBeVisible();
        await page.getByTestId("profile-settings").click();
        await pressTelegramBackButton(page);
        await expect(page.getByTestId("settings-screen")).toHaveCount(0);
        await expect(page.getByTestId("profile-settings")).toBeVisible();
      });

      test("Тесты: карточки (бейдж, название, результат, шеврон) и возврат на Главную из списка и детали", async ({ page }) => {
        const { consoleErrors } = await openAppAs(page, 997_707, { theme, backButton: true });
        await page.getByTestId("home-tests-row").click();
        await expect(page.getByTestId("tests-screen")).toBeVisible();
        const cards = page.getByTestId("test-card");
        await expect(cards.first()).toBeVisible();
        expect(await cards.count()).toBeGreaterThanOrEqual(2);
        for (let i = 0; i < (await cards.count()); i += 1) {
          const card = cards.nth(i);
          await expect(card.getByTestId("test-card-name")).not.toHaveText("");
          await expect(card.getByTestId("test-card-last")).not.toHaveText("");
          await expect(card.locator(".test-card-badge svg")).toBeVisible();
          await expect(card.locator("svg.test-card-chevron")).toBeVisible();
          const box = (await card.boundingBox())!;
          expect(box.height, "карточка не плоская строка").toBeGreaterThanOrEqual(56);
          expect(box.x + box.width).toBeLessThanOrEqual(width + 0.5);
        }
        const cardBg = luminance(await bg(page, '[data-testid="tests-list"]'));
        theme === "dark" ? expect(cardBg).toBeLessThan(0.3) : expect(cardBg).toBeGreaterThan(0.8);
        expect(EMOJI.test((await page.getByTestId("tests-screen").textContent()) ?? "")).toBe(false);
        await expectNoHorizontalOverflow(page, "Тесты");
        await snap(page, width, theme, "tests");

        // деталь → «← Назад» → список → Telegram BackButton → Главная
        await cards.first().click();
        await expect(page.getByTestId("test-detail")).toBeVisible();
        await expectNoHorizontalOverflow(page, "Деталь теста");
        await page.getByRole("button", { name: "← Назад" }).first().click();
        await expect(page.getByTestId("tests-screen")).toBeVisible();
        await expect(cards.first()).toBeVisible();
        // деталь → Telegram BackButton → список
        await cards.first().click();
        await expect(page.getByTestId("test-detail")).toBeVisible();
        await pressTelegramBackButton(page);
        await expect(page.getByTestId("tests-screen")).toBeVisible();
        // список → in-app «← Назад» → Главная
        await page.getByRole("button", { name: "← Назад" }).first().click();
        await expect(page.getByTestId("tests-screen")).toHaveCount(0);
        await expect(page.getByTestId("home-tests-row")).toBeVisible();
        // и ещё раз через Telegram BackButton из списка
        await page.getByTestId("home-tests-row").click();
        await expect(page.getByTestId("tests-screen")).toBeVisible();
        await pressTelegramBackButton(page);
        await expect(page.getByTestId("home-tests-row")).toBeVisible();
        expect(consoleErrors.filter((e) => !/wake ?lock/i.test(e))).toEqual([]);
      });

      test("Тесты из Профиля: деталь возвращает в Профиль", async ({ page }) => {
        await openAppAs(page, 997_707, { theme, backButton: true });
        await openTab(page, "Профиль");
        const cards = page.getByTestId("test-card");
        await expect(cards.first()).toBeVisible();
        await expectNoHorizontalOverflow(page, "Профиль с тестами");
        await cards.first().click();
        await expect(page.getByTestId("test-detail")).toBeVisible();
        await pressTelegramBackButton(page);
        await expect(page.getByTestId("test-detail")).toHaveCount(0);
        await expect(cards.first()).toBeVisible();
        await cards.first().click();
        await page.getByRole("button", { name: "← Назад" }).first().click();
        await expect(page.getByTestId("profile-settings")).toBeVisible();
      });
    });
  }
}
