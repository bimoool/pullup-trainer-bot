import type { Page } from "@playwright/test";

import { collectConsoleErrors, collectUnexpectedApiFailures } from "./assertions";
import { buildInitData, getTestBotToken } from "./initData";
import { mockTelegramWebApp, type TelegramMockOptions, type TelegramTheme } from "./telegramMock";

/**
 * Общий вход в приложение для сценариев — подписывает initData на
 * telegramId (данные под этот id уже должны быть посеяны заранее, см.
 * scripts/e2e_seed.py), кладёт его туда же, куда его кладёт реальный
 * Telegram-клиент (mockTelegramWebApp), открывает "/" и сразу начинает
 * слушать консоль/сетевые ответы — до первого запроса приложения, не
 * после. allowedApiStatuses — коды ответов /api/*, которые сам сценарий
 * ожидает и проверяет намеренно (по умолчанию сценарий не ждёт вообще
 * никаких ошибок API).
 */
export async function openAppAs(
  page: Page,
  telegramId: number,
  options: {
    allowedApiStatuses?: number[]; firstName?: string; theme?: TelegramTheme; backButton?: boolean;
    telegram?: Omit<TelegramMockOptions, "backButton">;
    /** issue #306: «v1» — новые старты на движке v1 (сценарии экрана v1, который обслуживает сессии
     * engine_version = 1); по умолчанию — Live Engine v2, как у пользователей. */
    liveEngine?: "v1" | "v2";
  } = {},
): Promise<{ consoleErrors: string[]; apiFailures: string[] }> {
  const consoleErrors = collectConsoleErrors(page);
  const apiFailures = collectUnexpectedApiFailures(page, options.allowedApiStatuses ?? []);

  const initDataRaw = buildInitData({ id: telegramId, firstName: options.firstName ?? "E2E" }, getTestBotToken());
  await mockTelegramWebApp(page, initDataRaw, options.theme, { ...options.telegram, backButton: options.backButton });
  if (options.liveEngine === "v1") {
    await page.addInitScript(() => window.localStorage.setItem("pullup:live-engine-version", "1"));
  }
  await page.goto("/");

  return { consoleErrors, apiFailures };
}

/** issue #306: сценарии экрана движка v1 (он обслуживает сессии engine_version = 1, начатые до Live Engine v2) —
 * новые старты в этом файле идут на движке v1 (тот же аварийный переключатель клиента, что
 * openAppAs({ liveEngine: "v1" })). Поведение Live Engine v2 — live-engine-v2.spec.ts и переведённые сценарии. */
export function useLiveEngineV1(api: { beforeEach: (fn: (args: { page: Page }) => Promise<void>) => void }): void {
  api.beforeEach(async ({ page }) => {
    await page.addInitScript(() => window.localStorage.setItem("pullup:live-engine-version", "1"));
  });
}
