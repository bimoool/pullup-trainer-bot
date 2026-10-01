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
export type TelegramTheme = "light" | "dark";

// Параметры темы, как их шлёт настоящий клиент Telegram (набор themeParams из
// Bot API), — main.tsx переносит их в CSS-переменные. "light" оставляет
// прежнее поведение мока (пустые themeParams → дефолты из index.css).
const THEME_PARAMS: Record<TelegramTheme, Record<string, string>> = {
  light: {},
  dark: {
    bg_color: "#17212b",
    text_color: "#f5f5f5",
    hint_color: "#708499",
    link_color: "#6ab3f3",
    button_color: "#5288c1",
    button_text_color: "#ffffff",
    secondary_bg_color: "#232e3c",
    section_bg_color: "#17212b",
    subtitle_text_color: "#708499",
    destructive_text_color: "#ec3942",
  },
};

/**
 * BackButton (issue #249). Opt-in: без `backButton: true` мок ведёт себя как
 * раньше (SDK недоступен → useBackButton ничего не делает). С флагом мок
 * повторяет то, что делает mockTelegramEnv из @telegram-apps/sdk: кладёт
 * launch params (версия 7.0 ≥ 6.1) в sessionStorage и объявляет
 * window.TelegramWebviewProxy.postEvent, куда SDK шлёт
 * web_app_setup_back_button; видимость кнопки запоминается в
 * window.__tgBackButtonVisible. Клик — pressTelegramBackButton().
 */
export async function pressTelegramBackButton(page: Page): Promise<void> {
  await page.evaluate(() => {
    // Тот же вид события, что доставляет настоящий клиент (и SDK-мок).
    window.dispatchEvent(
      new MessageEvent("message", {
        data: JSON.stringify({ eventType: "back_button_pressed", eventData: "" }),
        source: window.parent,
      }),
    );
  });
}

export async function isTelegramBackButtonVisible(page: Page): Promise<boolean> {
  return page.evaluate(() => (window as unknown as { __tgBackButtonVisible?: boolean }).__tgBackButtonVisible === true);
}

export async function mockTelegramWebApp(
  page: Page,
  initDataRaw: string,
  theme: TelegramTheme = "light",
  options: { backButton?: boolean } = {},
): Promise<void> {
  if (options.backButton) {
    await page.addInitScript(() => {
      const params = new URLSearchParams({
        tgWebAppPlatform: "tdesktop",
        tgWebAppThemeParams: "{}",
        tgWebAppVersion: "7.0",
      });
      sessionStorage.setItem("tapps/launchParams", JSON.stringify(params.toString()));
      (window as unknown as { TelegramWebviewProxy: unknown }).TelegramWebviewProxy = {
        postEvent: (eventType: string, eventData: string) => {
          if (eventType === "web_app_setup_back_button") {
            const { is_visible: visible } = JSON.parse(eventData || "{}") as { is_visible?: boolean };
            (window as unknown as { __tgBackButtonVisible: boolean }).__tgBackButtonVisible = visible === true;
          }
        },
      };
    });
  }
  await page.route("https://telegram.org/js/telegram-web-app.js", (route) =>
    route.fulfill({ status: 200, contentType: "application/javascript", body: "" }),
  );
  await page.addInitScript(({ raw, colorScheme, themeParams }) => {
    (window as unknown as { Telegram: unknown }).Telegram = {
      WebApp: {
        initData: raw,
        initDataUnsafe: {},
        version: "7.0",
        platform: "tdesktop",
        colorScheme,
        themeParams,
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
  }, { raw: initDataRaw, colorScheme: theme, themeParams: THEME_PARAMS[theme] });
}
