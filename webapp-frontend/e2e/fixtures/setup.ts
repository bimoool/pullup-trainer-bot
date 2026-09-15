import type { Page } from "@playwright/test";

import { collectConsoleErrors, collectUnexpectedApiFailures } from "./assertions";
import { buildInitData, getTestBotToken } from "./initData";
import { mockTelegramWebApp } from "./telegramMock";

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
  options: { allowedApiStatuses?: number[]; firstName?: string } = {},
): Promise<{ consoleErrors: string[]; apiFailures: string[] }> {
  const consoleErrors = collectConsoleErrors(page);
  const apiFailures = collectUnexpectedApiFailures(page, options.allowedApiStatuses ?? []);

  const initDataRaw = buildInitData({ id: telegramId, firstName: options.firstName ?? "E2E" }, getTestBotToken());
  await mockTelegramWebApp(page, initDataRaw);
  await page.goto("/");

  return { consoleErrors, apiFailures };
}
