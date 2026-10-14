import { expect, test, type Page } from "@playwright/test";

import { buildInitData, getTestBotToken } from "../fixtures/initData";
import { openAppAs } from "../fixtures/setup";

/**
 * Аудит staging (Telegram Web): «Отменить тренировку» не срабатывала. Mini App в Telegram Web живёт в iframe, где
 * window.confirm не показывается и сразу возвращает false. Отмена спрашивает через нативный WebApp.showConfirm
 * (Bot API 6.2+), серверный контракт прежний: событие `cancel` движка. Сид: scripts/e2e_seed.py live_engine 930621.
 * Узкий экран (320 px).
 */
test.use({ viewport: { width: 320, height: 640 }, isMobile: true, hasTouch: true });
test.setTimeout(90_000);

const TELEGRAM_ID = 930_621;

async function activeSession(page: Page) {
  const initData = buildInitData({ id: TELEGRAM_ID, firstName: "E2E" }, getTestBotToken());
  const response = await page.request.get("/api/v2/sessions/live/active", { headers: { "X-Telegram-Init-Data": initData } });
  return (await response.json()).session as { id: number; engine?: { state: { status: string } } } | null;
}

/** Как в Telegram Web: window.confirm заблокирован (false без диалога), нативное подтверждение отвечает `answer`. */
async function telegramWebConfirm(page: Page, answer: boolean) {
  await page.evaluate((ok) => {
    const w = window as unknown as {
      confirm: () => boolean; __asked: string[];
      Telegram: { WebApp: { showConfirm?: (message: string, callback: (confirmed: boolean) => void) => void } };
    };
    w.__asked = [];
    w.confirm = () => false;
    w.Telegram.WebApp.showConfirm = (message, callback) => {
      w.__asked.push(message);
      setTimeout(() => callback(ok), 0);
    };
  }, answer);
}

test("отмена тренировки в Telegram Web: нативное подтверждение; «Нет» ничего не меняет, «Да» отменяет на сервере", async ({ page }) => {
  const { apiFailures } = await openAppAs(page, TELEGRAM_ID);
  await page.getByRole("button", { name: "Планы" }).click();
  const group = page.locator(".plan-week-day-group").filter({ hasText: /^Движок: подходы/ });
  await group.getByRole("button", { name: /^Начать: / }).first().click();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await expect(page.getByText("Живая тренировка")).toBeVisible();
  await expect(page.getByTestId("engine-phase")).toBeVisible();
  const started = await activeSession(page);
  expect(started).not.toBeNull();

  await page.getByRole("button", { name: "Завершить" }).first().click();
  const cancel = page.getByTestId("engine-cancel");
  await expect(cancel).toBeVisible();

  await telegramWebConfirm(page, false);
  await cancel.click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { __asked: string[] }).__asked)).toEqual([
    "Отменить тренировку? Ничего не сохранится.",
  ]);
  await page.waitForTimeout(500);
  expect((await activeSession(page))?.id).toBe(started?.id); // «Нет» — тренировка идёт

  await telegramWebConfirm(page, true);
  const events = page.waitForResponse((r) => r.url().includes("/events") && r.request().method() === "POST");
  await cancel.click();
  expect((await events).status()).toBe(200);
  await expect.poll(async () => (await activeSession(page))?.id ?? null, { timeout: 10_000 }).toBeNull();
  expect(apiFailures).toEqual([]);
});
