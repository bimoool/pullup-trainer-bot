import { expect, test, type Page } from "@playwright/test";

import { noWakeLock, playSets } from "../../fixtures/builderFlow";
import { openTab } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import {
  emitTelegramEvent, isTelegramBackButtonVisible, isTelegramClosingConfirmationOn, pressTelegramBackButton, telegramCalls,
} from "../../fixtures/telegramMock";

// Платформа Telegram (#224): то, что десктопный Chromium без мока не видит. Мок — fixtures/telegramMock.ts
// (версия Bot API, safe area, журнал вызовов WebApp). Сиды 9988xx — scripts/e2e_seed_all.sh.
// 998801/998803/998805 (+retry): session_recovery (Home → «Тренировка восстановления»), 998811 — ready.
const TITLE = "Тренировка восстановления";

test.describe("Платформа Telegram", () => {
  test.use({ viewport: { width: 390, height: 800 } });
  test.setTimeout(120_000);

  const backVisible = (page: Page) => expect.poll(() => isTelegramBackButtonVisible(page));

  test("BackButton: скрыта на корневых вкладках, видна на деталях, один клик — один шаг назад", async ({ page }, testInfo) => {
    const { consoleErrors, apiFailures } = await openAppAs(page, 998_801 + testInfo.retry, {
      backButton: true, telegram: { version: "8.0" },
    });
    await expect(page.locator(".bottom-tabbar")).toBeVisible();

    // корневые вкладки — без кнопки
    await backVisible(page).toBe(false);
    for (const tab of ["Планы", "Журнал", "Аналитика", "Профиль", "Главная"]) {
      await openTab(page, tab);
      await page.waitForTimeout(50);
      expect(await isTelegramBackButtonVisible(page), `BackButton на корневой вкладке «${tab}»`).toBe(false);
    }

    // Workout Detail: видна; клик возвращает на Главную ровно на один шаг и снова прячется
    await page.getByTestId("my-workout-card").filter({ hasText: TITLE }).click();
    await expect(page.getByRole("button", { name: "Добавить в план" })).toBeVisible();
    await backVisible(page).toBe(true);
    await pressTelegramBackButton(page);
    await expect(page.getByTestId("my-workout-card").filter({ hasText: TITLE })).toBeVisible();
    await backVisible(page).toBe(false);

    // Профиль → Настройки (вложенный экран): видна, клик → Профиль, не дальше
    await openTab(page, "Профиль");
    await page.getByTestId("profile-settings").click();
    await expect(page.getByTestId("settings-screen")).toBeVisible();
    await backVisible(page).toBe(true);
    await pressTelegramBackButton(page);
    await expect(page.getByTestId("profile-settings")).toBeVisible();
    await expect(page.getByTestId("settings-screen")).toHaveCount(0);
    await backVisible(page).toBe(false);

    // Профиль → FAQ (раньше без BackButton): видна, клик возвращает в Профиль
    await page.getByRole("button", { name: /Как выбрать резину/ }).click();
    await backVisible(page).toBe(true);
    await pressTelegramBackButton(page);
    await expect(page.getByTestId("profile-settings")).toBeVisible();
    await backVisible(page).toBe(false);

    expect(noWakeLock(consoleErrors)).toEqual([]);
    expect(apiFailures).toEqual([]);
  });

  test("старт: ready/expand/запрет свайпа (8.0), цвета хрома по светлой оболочке, закрытие с подтверждением только в живой сессии", async ({ page }, testInfo) => {
    const { consoleErrors, apiFailures } = await openAppAs(page, 998_803 + testInfo.retry, {
      backButton: true, theme: "light", telegram: { version: "8.0" },
    });
    await expect(page.locator(".bottom-tabbar")).toBeVisible();

    const calls = await telegramCalls(page);
    expect(calls).toEqual(expect.arrayContaining(["ready", "expand", "disableVerticalSwipes"]));
    // светлая оболочка: страница #f2f2f7, поверхность (нижняя навигация/карточки) #ffffff
    expect(calls).toEqual(expect.arrayContaining(["setHeaderColor:#f2f2f7", "setBackgroundColor:#f2f2f7", "setBottomBarColor:#ffffff"]));
    expect(await isTelegramClosingConfirmationOn(page)).toBe(false);

    // Планы → Начать → живая сессия
    await page.getByTestId("my-workout-card").filter({ hasText: TITLE }).click();
    await page.getByRole("button", { name: "Добавить в план" }).click();
    await page.getByRole("button", { name: "Свободный пул" }).click();
    await page.getByRole("button", { name: "Добавить", exact: true }).click();
    const group = page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${TITLE}`) });
    await group.getByRole("button", { name: /^Начать: / }).click();
    // экран подготовки — тоже без подтверждения (данных ещё нет)
    expect(await isTelegramClosingConfirmationOn(page)).toBe(false);
    const started = page.waitForResponse((r) => r.url().includes("/api/v2/sessions/live") && r.request().method() === "POST");
    await page.getByRole("button", { name: "Начать", exact: true }).click();
    const sessionId = ((await (await started).json()) as { id: number }).id;
    await expect(page.getByText("Живая тренировка")).toBeVisible();
    await expect.poll(() => isTelegramClosingConfirmationOn(page)).toBe(true);
    expect(await telegramCalls(page)).toContain("enableClosingConfirmation");

    await playSets(page, ["8"], false);
    await expect.poll(() => isTelegramClosingConfirmationOn(page)).toBe(true);
    await backVisible(page).toBe(true);

    // завершение (BackButton → подтверждение → итоги): флаг выключается, BackButton скрыта
    page.on("dialog", (dialog) => void dialog.accept());
    const complete = page.waitForResponse((r) => r.url().includes(`/api/v2/sessions/live/${sessionId}/complete`));
    await pressTelegramBackButton(page);
    expect((await complete).status()).toBe(200);
    await expect(page.getByText("Тренировка завершена")).toBeVisible();
    await expect.poll(() => isTelegramClosingConfirmationOn(page)).toBe(false);
    expect(await telegramCalls(page)).toContain("disableClosingConfirmation");

    expect(noWakeLock(consoleErrors)).toEqual([]);
    expect(apiFailures).toEqual([]);
  });

  test("версии: до 7.7 нет disableVerticalSwipes, до 7.10 нет setBottomBarColor, до 6.2 нет подтверждения закрытия", async ({ page }, testInfo) => {
    const { apiFailures } = await openAppAs(page, 998_805 + testInfo.retry, { theme: "dark", telegram: { version: "6.1" } });
    await expect(page.locator(".bottom-tabbar")).toBeVisible();
    const calls = await telegramCalls(page);
    expect(calls).toEqual(expect.arrayContaining(["ready", "expand"]));
    expect(calls.some((entry) => entry === "disableVerticalSwipes")).toBe(false);
    expect(calls.some((entry) => entry.startsWith("setBottomBarColor"))).toBe(false);
    // 6.1: setHeaderColor — только ключом темы (hex — с 6.9); тёмная оболочка: страница = bg (#17212b)
    expect(calls).toEqual(expect.arrayContaining(["setHeaderColor:bg_color", "setBackgroundColor:#17212b"]));
    expect(apiFailures).toEqual([]);
  });

  test("safe area (Bot API 8.0): нижняя навигация и контент сдвинуты на инсет, событие safeAreaChanged обновляет отступы", async ({ page }, testInfo) => {
    const { apiFailures } = await openAppAs(page, 998_806 + testInfo.retry, {
      theme: "dark",
      telegram: {
        version: "8.0",
        safeAreaInset: { top: 59, bottom: 34, left: 0, right: 0 },
        contentSafeAreaInset: { top: 44, bottom: 0, left: 0, right: 0 },
      },
    });
    const nav = page.locator(".bottom-tabbar");
    await expect(nav).toBeVisible();
    const px = (selector: string, property: string) =>
      page.evaluate(([sel, prop]) => parseFloat(getComputedStyle(document.querySelector(sel) as Element).getPropertyValue(prop)), [selector, property]);

    expect(await px(".bottom-tabbar", "padding-bottom")).toBe(34);
    // контент: шапка Telegram (59 + 44) + штатные 8px сверху; снизу — навигация 58 + 20 + 34
    expect(await px(".app-shell", "padding-top")).toBe(8 + 59 + 44);
    expect(await px(".app-shell", "padding-bottom")).toBe(58 + 20 + 34);
    // нижняя навигация целиком в окне и не уходит под инсет
    const box = await nav.boundingBox();
    expect(box).not.toBeNull();
    expect(Math.round((box?.y ?? 0) + (box?.height ?? 0))).toBeLessThanOrEqual(800);

    // клиент сменил инсеты (например, выход из полноэкранного режима)
    await page.evaluate(() => {
      const webApp = (window as unknown as { Telegram: { WebApp: Record<string, unknown> } }).Telegram.WebApp;
      webApp.safeAreaInset = { top: 0, bottom: 0, left: 0, right: 0 };
      webApp.contentSafeAreaInset = { top: 0, bottom: 0, left: 0, right: 0 };
    });
    await emitTelegramEvent(page, "safeAreaChanged");
    await emitTelegramEvent(page, "contentSafeAreaChanged");
    await expect.poll(() => px(".bottom-tabbar", "padding-bottom")).toBe(0);
    expect(await px(".app-shell", "padding-top")).toBe(8);
    expect(apiFailures).toEqual([]);
  });

  test("без инсетов (7.0, как до аудита): отступы сверху/снизу штатные", async ({ page }, testInfo) => {
    const { apiFailures } = await openAppAs(page, 998_805 + testInfo.retry);
    await expect(page.locator(".bottom-tabbar")).toBeVisible();
    const padding = await page.evaluate(() => ({
      nav: getComputedStyle(document.querySelector(".bottom-tabbar") as Element).paddingBottom,
      top: getComputedStyle(document.querySelector(".app-shell") as Element).paddingTop,
    }));
    expect(padding).toEqual({ nav: "0px", top: "8px" });
    expect(apiFailures).toEqual([]);
  });

  test("десятичная запятая: «78,5» принимается как 78.5 и сохраняется", async ({ page }, testInfo) => {
    const { consoleErrors, apiFailures } = await openAppAs(page, 998_811 + testInfo.retry);
    await openTab(page, "Профиль");
    await page.getByTestId("profile-settings").click();
    const weight = page.getByRole("textbox", { name: "Вес" });
    await expect(weight).toHaveAttribute("inputmode", "decimal");
    await weight.fill("");
    await weight.pressSequentially("78,5");
    await expect(weight).toHaveValue("78.5");
    // буквы и вторая запятая не проходят
    await weight.pressSequentially("кг,1");
    await expect(weight).toHaveValue("78.51");
    await weight.fill("78,5");
    await expect(weight).toHaveValue("78.5");
    await page.getByTestId("settings-save").click();
    await expect(page.getByTestId("profile-weight")).toHaveText("Вес: 78.5 кг");
    expect(noWakeLock(consoleErrors)).toEqual([]);
    expect(apiFailures).toEqual([]);
  });

  test("просроченный initData (401): понятная подсказка «открой заново» и кнопка «Закрыть»", async ({ page }) => {
    await page.route("**/api/hello", (route) =>
      route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify({ detail: "Invalid Telegram initData" }) }),
    );
    await openAppAs(page, 998_811, { allowedApiStatuses: [401] });
    await expect(page.getByText(/Сессия Telegram устарела/)).toBeVisible();
    await expect(page.getByText("Invalid Telegram initData")).toHaveCount(0);
    await page.getByTestId("session-expired-close").click();
    expect(await telegramCalls(page)).toContain("close");
  });
});
