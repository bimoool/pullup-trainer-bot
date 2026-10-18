// Определение способа входа (владелец — WEB-AUTH; до его работы — прежнее поведение Mini App без изменений).
// Результат: Telegram (initData от клиента), browser (защищённая браузерная сессия), login (нужен вход),
// error (не удалось определить / открыто не из Telegram, браузерный вход отключён).
import { retrieveLaunchParams } from "@telegram-apps/sdk";

export type AuthResult =
  | { kind: "telegram"; initDataRaw: string }
  | { kind: "browser"; initDataRaw: string }
  | { kind: "login" }
  | { kind: "error"; message: string };

type TelegramWebApp = { initData?: string; version?: string; platform?: string };

/**
 * issue #28 — предыдущий текст ошибки ("initDataRaw is empty — открыто не
 * из Telegram?") был одинаков и для реального бага (initData не долетел),
 * и для заведомо ожидаемого случая (страница открыта напрямую в обычном
 * браузере — там initData не появится никогда, ни при какой конфигурации
 * кнопки). Со стороны пользователя оба выглядят идентично, что и породило
 * ложный след в issue: кнопка в app/bot/keyboards.py уже
 * KeyboardButton(web_app=WebAppInfo(...)), не обычная url= ссылка — код
 * это подтверждает, а сам факт "то же самое в браузере" ничего не
 * доказывает. Раз ошибка внутри настоящего Telegram-клиента всё равно
 * повторяется — точку отказа даёт только больше сырых данных с места
 * (что вернул retrieveLaunchParams, есть ли вообще window.Telegram.WebApp,
 * какой у него version/platform), не гадание по одной фразе.
 */
function describeInitDataFailure(retrieveError: string | undefined, telegramWebApp: TelegramWebApp | undefined) {
  const parts = [
    `retrieveLaunchParams: ${retrieveError ?? "вернул пустой initDataRaw без исключения"}`,
    telegramWebApp
      ? `window.Telegram.WebApp: есть (version=${telegramWebApp.version ?? "?"}, platform=${telegramWebApp.platform ?? "?"})`
      : "window.Telegram.WebApp: отсутствует",
    `location.href: ${window.location.href}`,
  ];
  return parts.join(" | ");
}

/** Прежняя цепочка Mini App (issues #15, #23, #28): launch params из URL, запасной источник — мост telegram-web-app.js. */
export async function resolveAuth(): Promise<AuthResult> {
  let initDataRaw: string | undefined;
  let retrieveError: string | undefined;
  try {
    initDataRaw = retrieveLaunchParams().initDataRaw;
  } catch (error) {
    retrieveError = error instanceof Error ? error.message : String(error);
  }
  const telegramWebApp = (window as unknown as { Telegram?: { WebApp?: TelegramWebApp } }).Telegram?.WebApp;
  if (!initDataRaw) {
    initDataRaw = telegramWebApp?.initData;
  }
  if (!initDataRaw) {
    return {
      kind: "error",
      message: `initDataRaw is empty — открыто не из Telegram? [${describeInitDataFailure(retrieveError, telegramWebApp)}]`,
    };
  }
  return { kind: "telegram", initDataRaw };
}
