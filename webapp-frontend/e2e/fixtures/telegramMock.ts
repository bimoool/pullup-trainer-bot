import type { Page } from "@playwright/test";

/**
 * App.tsx читает initData в таком порядке: retrieveLaunchParams() (парсит
 * launch-параметры из URL/performance entry/sessionStorage) → фолбэк на
 * window.Telegram.WebApp.initData, куда его кладёт мост telegram-web-app.js
 * реального Telegram-клиента (issue #23/#28, см. CLAUDE.md — оба источника
 * подтверждены живыми инцидентами). Подделывать первый путь означало бы
 * подсовывать launch-параметры в URL/sessionStorage до навигации — сложнее
 * и более хрупко, чем положить initData туда же, куда его кладёт реальный
 * мост: page.addInitScript выполняется ДО загрузки любого скрипта страницы
 * (включая React-бандл), так что фолбэк в App.tsx срабатывает как обычный
 * путь кода, не через подмену fetch/API целиком.
 */
export async function mockTelegramWebApp(page: Page, initDataRaw: string): Promise<void> {
  await page.addInitScript((raw: string) => {
    (window as unknown as { Telegram: unknown }).Telegram = {
      WebApp: {
        initData: raw,
        initDataUnsafe: {},
        version: "7.0",
        platform: "tdesktop",
        colorScheme: "light",
        themeParams: {},
        ready: () => {},
        expand: () => {},
        close: () => {},
        setHeaderColor: () => {},
        setBackgroundColor: () => {},
        onEvent: () => {},
        offEvent: () => {},
        HapticFeedback: {
          impactOccurred: () => {},
          notificationOccurred: () => {},
          selectionChanged: () => {},
        },
      },
    };
  }, initDataRaw);
}
