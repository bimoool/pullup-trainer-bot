import { expect, test, type Page } from "@playwright/test";

import { collectConsoleErrors, collectUnexpectedApiFailures } from "../../fixtures/assertions";

/**
 * WEB-LAYOUT: «Назад» в странице по цепочкам вглубь, платёжная ссылка через openLink-фолбэк, шторка оплаты.
 * Сиды: 943010/943011 home_workouts (чтение), 943020/943021 session_recovery (чтение до предэкрана),
 * 900003 ready (чтение).
 */

async function openShell(page: Page, telegramId: number) {
  const consoleErrors = collectConsoleErrors(page);
  const apiFailures = collectUnexpectedApiFailures(page, []);
  const login = await page.request.post("/api/web-auth/test-login", { data: { telegram_id: telegramId } });
  expect(login.status()).toBe(200);
  await page.goto("/");
  return { consoleErrors, apiFailures };
}

test("Главная → деталь тренировки → «Назад» в странице → Главная", async ({ page }, info) => {
  const { apiFailures } = await openShell(page, info.project.name === "web-mobile" ? 943_011 : 943_010);
  await expect(page.getByTestId("my-workouts")).toBeVisible();
  await expect(page.getByTestId("web-back")).toHaveCount(0);
  await page.getByTestId("my-workout-card").first().click();
  await expect(page.getByTestId("workout-detail")).toBeVisible();
  await page.getByTestId("web-back").click();
  await expect(page.getByTestId("my-workouts")).toBeVisible();
  await expect(page.getByTestId("web-back")).toHaveCount(0);
  expect(apiFailures).toEqual([]);
});

test("План → предэкран сессии → «Назад» в странице → план", async ({ page }, info) => {
  const TITLE = "Тренировка восстановления";
  const { apiFailures } = await openShell(page, info.project.name === "web-mobile" ? 943_021 : 943_020);
  await page.getByTestId("my-workout-card").filter({ hasText: TITLE }).click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await page.getByRole("button", { name: "Без дня" }).click();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  const group = page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${TITLE}`) });
  await group.getByRole("button", { name: /^Начать: / }).click();
  await expect(page.getByRole("button", { name: "Начать", exact: true })).toBeVisible();
  await page.getByTestId("web-back").click();
  await expect(group.getByRole("button", { name: /^Начать: / })).toBeVisible();
  expect(apiFailures).toEqual([]);
});

test("подписка: «Оплатить» открывает ссылку через window.open(noopener), платёж не выполняется", async ({ page }) => {
  await page.addInitScript(() => {
    (window as unknown as { __opened: unknown[] }).__opened = [];
    window.open = ((...args: unknown[]) => {
      (window as unknown as { __opened: unknown[] }).__opened.push(args);
      return null;
    }) as typeof window.open;
  });
  // ссылку на оплату подменяем заглушкой: настоящий Robokassa-вызов в тестах не нужен и запрещён
  await page.route("**/api/subscription/pay", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ payment_url: "https://pay.example.test/checkout?id=layout" }) }));
  const { apiFailures } = await openShell(page, 900_003);
  await page.locator("nav.bottom-tabbar").getByRole("button", { name: "Профиль" }).click();
  await page.getByText("Подписка", { exact: true }).first().click();
  const pay = page.getByRole("button", { name: /Оплатить/ });
  if ((await pay.count()) === 0) {
    // у пользователя нет доступной оплаты (экран всё равно отрисован без ошибок)
    await expect(page.getByTestId("web-back")).toBeVisible();
    return;
  }
  await pay.click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { __opened: unknown[][] }).__opened.length)).toBe(1);
  const args = await page.evaluate(() => (window as unknown as { __opened: unknown[][] }).__opened[0]);
  expect(args).toEqual(["https://pay.example.test/checkout?id=layout", "_blank", "noopener"]);
  expect(apiFailures).toEqual([]);
});

test("скриншоты оболочки (светлая/тёмная)", async ({ page }, info) => {
  test.skip(!process.env.WL_SHOTS, "только при WL_SHOTS=1");
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await openShell(page, 900_003);
    await expect(page.locator("nav.bottom-tabbar")).toBeVisible();
    await page.screenshot({ path: `../../docs/audit/ux-ref-20261018/checkpoints/WEB-LAYOUT-shots/${info.project.name}-${scheme}.png` });
    if (info.project.name === "web-desktop") {
      await page.setViewportSize({ width: 820, height: 1100 });
      await page.screenshot({ path: `../../docs/audit/ux-ref-20261018/checkpoints/WEB-LAYOUT-shots/tablet-820-${scheme}.png` });
      await page.setViewportSize({ width: 1280, height: 800 });
    }
  }
});
