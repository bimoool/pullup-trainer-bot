// Среда выполнения: Mini App внутри Telegram или обычный браузер. Чистая часть без импортов SDK/React
// (юнит-тесты: tests/platformRuntime.test.ts). Владелец — WEB-LAYOUT.
//
// Режим, который знает React (usePlatform().mode), приходит асинхронно (после resolveAuth в App.tsx), а
// confirmAction / openExternalLink / стек «Назад» / подтверждение закрытия — не React-код. Поэтому здесь
// модульная переменная: стартует от эвристики, AppShell синхронизирует её с реальным режимом.

export type RuntimeWebApp = { initData?: unknown; platform?: unknown } | null | undefined;
export type RuntimeLocation = { hash?: string; search?: string } | null | undefined;

const LAUNCH_PARAM_MARKERS = ["tgWebAppData", "tgWebAppVersion", "tgWebAppPlatform"];

/**
 * Браузер ли это. Telegram-признаки (любого достаточно): непустой WebApp.initData, платформа клиента
 * кроме "unknown" (telegram-web-app.js в обычном браузере создаёт WebApp с platform "unknown" и пустым
 * initData), launch params в URL. Нет ни одного — браузер.
 */
export function detectBrowserRuntime(webApp: RuntimeWebApp, location: RuntimeLocation): boolean {
  if (typeof webApp?.initData === "string" && webApp.initData !== "") {
    return false;
  }
  if (webApp && !(typeof webApp.platform === "string" && (webApp.platform === "" || webApp.platform === "unknown"))) {
    // Настоящий telegram-web-app.js всегда выставляет platform строкой ("unknown" вне Telegram); любой другой
    // мост (платформа клиента, нестандартный объект) считаем Telegram.
    return false;
  }
  const haystack = `${location?.hash ?? ""}&${location?.search ?? ""}`;
  return !LAUNCH_PARAM_MARKERS.some((marker) => haystack.includes(marker));
}

let browserRuntime: boolean | null = null;

function detectNow(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  const webApp = (window as unknown as { Telegram?: { WebApp?: RuntimeWebApp } }).Telegram?.WebApp;
  return detectBrowserRuntime(webApp, window.location);
}

/** Браузерный режим? До явной установки — эвристика (кэшируется). */
export function isBrowserRuntime(): boolean {
  if (browserRuntime === null) {
    browserRuntime = detectNow();
  }
  return browserRuntime;
}

/** Явная установка (AppShell по usePlatform().mode). Возвращает true, если значение изменилось. */
export function setBrowserRuntime(value: boolean): boolean {
  const changed = browserRuntime !== value;
  browserRuntime = value;
  if (typeof document !== "undefined") {
    if (value) {
      document.documentElement.dataset.vpRuntime = "browser";
    } else {
      delete document.documentElement.dataset.vpRuntime;
    }
  }
  return changed;
}

/** Для тестов. */
export function resetRuntimeForTests(): void {
  browserRuntime = null;
}
