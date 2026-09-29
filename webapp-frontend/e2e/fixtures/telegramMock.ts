import type { Page } from "@playwright/test";

/**
 * App.tsx читает initData в таком порядке: retrieveLaunchParams() (парсит
 * launch-параметры из URL/performance entry/sessionStorage) → фолбэк на
 * window.Telegram.WebApp.initData, куда его кладёт мост telegram-web-app.js
 * реального Telegram-клиента (issue #23/#28, см. docs/mini-app.md — оба источника
 * подтверждены живыми инцидентами). Подделывать первый путь означало бы
 * подсовывать launch-параметры в URL/sessionStorage до навигации — сложнее
 * и более хрупко, чем положить initData туда же, куда его кладёт реальный
 * мост: page.addInitScript выполняется ДО загрузки любого скрипта страницы
 * (включая React-бандл), так что фолбэк в App.tsx срабатывает как обычный
 * путь кода, не через подмену fetch/API целиком.
 *
 * Реальная находка (issue #126, разбор 3-го прогона CI — все три сценария
 * падали одинаково на первом же ожидаемом экране, не только "ready"):
 * webapp-frontend/index.html грузит настоящий
 * https://telegram.org/js/telegram-web-app.js блокирующим <script> в
 * <head>, БЕЗ async/defer — Playwright гарантирует, что addInitScript
 * выполняется раньше ЛЮБОГО скрипта страницы, но этот скрипт всё равно
 * выполняется ПОСЛЕ addInitScript и, будучи запущен вне настоящего
 * Telegram-клиента, сам создаёт window.Telegram.WebApp с собственным
 * (пустым) initData — целиком ПЕРЕЗАПИСЫВАЯ объект, который мы только что
 * положили, а не дополняя его. Итог одинаков на каждом сценарии: App.tsx
 * получает telegramWebApp.initData==="" и падает в "initDataRaw is empty"
 * ещё до первого запроса к /api/hello — универсально, не зависит от
 * seed-данных конкретного telegram_id, что и объясняет одинаковое падение
 * всех трёх спеков. Перехватываем сам сетевой запрос к этому скрипту и
 * отдаём пустой файл — тогда наш мок остаётся единственным источником
 * window.Telegram, независимо от порядка выполнения тегов в <head>.
 */
export async function mockTelegramWebApp(page: Page, initDataRaw: string): Promise<void> {
  await page.route("https://telegram.org/js/telegram-web-app.js", (route) =>
    route.fulfill({ status: 200, contentType: "application/javascript", body: "" }),
  );
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
