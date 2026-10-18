import { expect, test, type Page } from "@playwright/test";

import { collectConsoleErrors, collectUnexpectedApiFailures } from "../../fixtures/assertions";

/**
 * WEB-LAYOUT: оболочка в браузерном режиме (проекты web-desktop 1280x800 / web-mobile 390x844).
 * Сиды: ready 900003 (только чтение), 943001/943002 — журнал для удаления (нужен пересев перед повторным прогоном).
 */

/** Браузерный вход через test-login WEB-AUTH (cookie-сессия), затем открытие приложения. */
async function openShell(page: Page, telegramId: number) {
  const consoleErrors = collectConsoleErrors(page);
  const apiFailures = collectUnexpectedApiFailures(page, []);
  const login = await page.request.post("/api/web-auth/test-login", { data: { telegram_id: telegramId } });
  expect(login.status()).toBe(200);
  await page.goto("/");
  return { consoleErrors, apiFailures };
}

async function noHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test("навигация: боковая на десктопе, нижняя на телефоне; aria-current и переключение вкладок", async ({ page }, info) => {
  const { apiFailures, consoleErrors } = await openShell(page, 900_003);
  const nav = page.locator("nav.bottom-tabbar");
  await expect(nav).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-vp-runtime", "browser");
  const box = (await nav.boundingBox())!;
  const viewport = page.viewportSize()!;
  if (info.project.name === "web-desktop") {
    expect(box.x).toBe(0);
    expect(box.y).toBe(0);
    expect(box.width).toBeGreaterThan(180);
    expect(box.width).toBeLessThan(300);
    expect(Math.round(box.height)).toBe(viewport.height);
  } else {
    expect(box.width).toBe(viewport.width);
    expect(box.y + box.height).toBeCloseTo(viewport.height, 0);
    expect(box.height).toBeLessThan(100);
  }
  await expect(nav.getByRole("button", { name: "Главная" })).toHaveAttribute("aria-current", "page");
  await nav.getByRole("button", { name: "Профиль" }).click();
  await expect(nav.getByRole("button", { name: "Профиль" })).toHaveAttribute("aria-current", "page");
  await expect(nav.getByRole("button", { name: "Главная" })).not.toHaveAttribute("aria-current", "page");
  await noHorizontalOverflow(page);
  const signOut = page.getByTestId("sign-out");
  await expect(signOut).toBeVisible();
  const sb = (await signOut.boundingBox())!;
  expect(sb.x).toBeGreaterThanOrEqual(0);
  expect(sb.x + sb.width).toBeLessThanOrEqual(viewport.width);
  expect(apiFailures).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

test("центральная колонка: ограничена по ширине на десктопе, не выходит за экран на телефоне", async ({ page }, info) => {
  await openShell(page, 900_003);
  const shell = page.locator(".app-shell");
  await expect(shell).toBeVisible();
  await expect(page.locator("nav.bottom-tabbar")).toBeVisible();
  const box = (await shell.boundingBox())!;
  if (info.project.name === "web-desktop") {
    expect(box.width).toBeLessThanOrEqual(761);
    const nav = (await page.locator("nav.bottom-tabbar").boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(nav.x + nav.width);
  } else {
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  }
});

test("«Назад» в странице: вглубь Профиль → Замеры и обратно; на корне кнопки нет", async ({ page }) => {
  const { apiFailures } = await openShell(page, 900_003);
  await expect(page.getByTestId("web-back")).toHaveCount(0);
  await page.getByRole("button", { name: "Профиль" }).click();
  await page.getByTestId("profile-weight").click();
  const back = page.getByTestId("web-back");
  await expect(back).toBeVisible();
  await expect(back).toHaveText(/Назад/);
  await back.click();
  await expect(page.getByTestId("web-back")).toHaveCount(0);
  await expect(page.getByTestId("profile-weight")).toBeVisible();
  // история браузера не засорена: ушли с приложения одним шагом назад
  expect(await page.evaluate(() => window.history.length)).toBeLessThanOrEqual(2);
  expect(apiFailures).toEqual([]);
});

for (const scheme of ["light", "dark"] as const) {
  test(`тема по prefers-color-scheme: ${scheme}`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await openShell(page, 900_003);
    await expect(page.locator("nav.bottom-tabbar")).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-vp-scheme", scheme);
    const colors = await page.evaluate(() => {
      const css = getComputedStyle(document.documentElement);
      return { bg: getComputedStyle(document.body).backgroundColor, text: getComputedStyle(document.body).color, tg: css.getPropertyValue("--tg-bg-color").trim() };
    });
    const lum = (rgb: string) => {
      const [r, g, b] = rgb.match(/\d+/g)!.map(Number);
      return (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    };
    if (scheme === "dark") {
      expect(lum(colors.bg)).toBeLessThan(0.3);
      expect(lum(colors.text)).toBeGreaterThan(0.7);
    } else {
      expect(lum(colors.bg)).toBeGreaterThan(0.7);
      expect(lum(colors.text)).toBeLessThan(0.3);
    }
  });
}

for (const width of [320, 1920]) {
  test(`без горизонтального переполнения @${width}px на основных вкладках`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 320 ? 700 : 1000 });
    await openShell(page, 900_003);
    for (const tab of ["Главная", "Планы", "Журнал", "Профиль"]) {
      const button = page.locator("nav.bottom-tabbar").getByRole("button", { name: tab });
      if (await button.count()) {
        await button.click();
        await page.waitForTimeout(250);
        await noHorizontalOverflow(page);
      }
    }
  });
}

test("подтверждение: шторка вместо window.confirm — «Нет» сохраняет, «Да» удаляет", async ({ page }, info) => {
  await page.addInitScript(() => {
    window.confirm = () => {
      throw new Error("window.confirm не должен вызываться в браузерном режиме");
    };
  });
  const { apiFailures } = await openShell(page, info.project.name === "web-mobile" ? 943_002 : 943_001);
  await page.locator("nav.bottom-tabbar").getByRole("button", { name: "Журнал" }).click();
  const legacy = page.locator(".history-card:not(.history-card-clickable)");
  const card13 = legacy.filter({ hasText: "максимум 13" });
  await expect(legacy).toHaveCount(4);
  await card13.getByRole("button", { name: /Удалить/ }).click();
  const sheet = page.getByTestId("web-confirm");
  await expect(sheet).toBeVisible();
  await expect(sheet).toContainText("Удалить эту тренировку");
  await expect(page.getByTestId("web-confirm-cancel")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(sheet).toHaveCount(0);
  await expect(legacy).toHaveCount(4);
  await card13.getByRole("button", { name: /Удалить/ }).click();
  await page.getByTestId("web-confirm-ok").click();
  await expect(legacy).toHaveCount(3);
  expect(apiFailures).toEqual([]);
});
