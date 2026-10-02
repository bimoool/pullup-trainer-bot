// Платформа Telegram WebApp (#224, аудит «Платформа Telegram»): всё, что десктопный Chromium в E2E
// не видит, а на iPhone/Android ломается. Модуль состоит из чистых помощников (версии Bot API,
// математика отступов, счётчик «подтверждения закрытия») и тонкой обвязки над window.Telegram.WebApp.
// Любой вызов защищён: вне Telegram (обычный браузер) и на старых клиентах всё превращается в no-op.
// Чистая часть без импортов из SDK/React — её проверяют юнит-тесты (tests/telegramPlatform.test.ts).

export type Insets = { top: number; bottom: number; left: number; right: number };

export type WebAppApi = {
  version?: string;
  platform?: string;
  isVersionAtLeast?: (version: string) => boolean;
  ready?: () => void;
  expand?: () => void;
  close?: () => void;
  disableVerticalSwipes?: () => void;
  enableClosingConfirmation?: () => void;
  disableClosingConfirmation?: () => void;
  setHeaderColor?: (color: string) => void;
  setBackgroundColor?: (color: string) => void;
  setBottomBarColor?: (color: string) => void;
  onEvent?: (event: string, handler: () => void) => void;
  offEvent?: (event: string, handler: () => void) => void;
  openLink?: (url: string, options?: { try_instant_view?: boolean }) => void;
  openTelegramLink?: (url: string) => void;
  safeAreaInset?: Partial<Insets>;
  contentSafeAreaInset?: Partial<Insets>;
  themeParams?: Record<string, string>;
  colorScheme?: "light" | "dark";
};

/** Минимальные версии Bot API для методов, которыми пользуется Mini App. */
export const MIN_VERSION = {
  setColors: "6.1", // setHeaderColor (ключ) / setBackgroundColor
  closingConfirmation: "6.2",
  headerColorHex: "6.9", // setHeaderColor принимает #RRGGBB
  disableVerticalSwipes: "7.7",
  setBottomBarColor: "7.10",
  safeArea: "8.0", // safeAreaInset / contentSafeAreaInset (+ fullscreen)
} as const;

export function getWebApp(): WebAppApi | undefined {
  if (typeof window === "undefined") {
    return undefined;
  }
  return (window as unknown as { Telegram?: { WebApp?: WebAppApi } }).Telegram?.WebApp;
}

/** Сравнение версий вида «7.10» (числовое по сегментам: 7.10 > 7.9). */
export function compareVersions(a: string, b: string): number {
  const left = a.split(".").map((part) => Number.parseInt(part, 10) || 0);
  const right = b.split(".").map((part) => Number.parseInt(part, 10) || 0);
  const length = Math.max(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    const diff = (left[index] ?? 0) - (right[index] ?? 0);
    if (diff !== 0) {
      return diff > 0 ? 1 : -1;
    }
  }
  return 0;
}

/**
 * Поддерживает ли клиент метод, появившийся в Bot API `required`. Источник версии — WebApp.version
 * (строка); если её нет, пробуем WebApp.isVersionAtLeast; нет ничего — «не поддерживает»
 * (для новых методов безопаснее не вызывать, чем вызвать пустышку).
 */
export function isVersionAtLeast(webApp: Pick<WebAppApi, "version" | "isVersionAtLeast"> | undefined, required: string): boolean {
  if (!webApp) {
    return false;
  }
  if (typeof webApp.version === "string" && webApp.version !== "") {
    return compareVersions(webApp.version, required) >= 0;
  }
  if (typeof webApp.isVersionAtLeast === "function") {
    try {
      return webApp.isVersionAtLeast(required) === true;
    } catch {
      return false;
    }
  }
  return false;
}

// ---------- отступы (safe area) ----------

function nonNegative(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
}

export function normalizeInsets(raw: Partial<Insets> | undefined): Insets {
  return { top: nonNegative(raw?.top), bottom: nonNegative(raw?.bottom), left: nonNegative(raw?.left), right: nonNegative(raw?.right) };
}

/**
 * Итоговый отступ стороны: системный вырез (env(safe-area-inset-*) или WebApp.safeAreaInset —
 * это одно и то же железо, берём большее, не складываем) + область Telegram-интерфейса
 * (contentSafeAreaInset: шапка с «Закрыть/…» в полноэкранном режиме). Та же формула в CSS —
 * src/telegram-safe-area.css (--vp-safe-top / --vp-safe-bottom).
 */
export function effectiveInsetPx(envPx: number, safePx: number, contentPx: number): number {
  return Math.max(nonNegative(envPx), nonNegative(safePx)) + nonNegative(contentPx);
}

/** CSS-переменные в тех же именах, что выставляет telegram-web-app.js (px). */
export function insetCssVars(safe: Insets, content: Insets): Record<string, string> {
  const vars: Record<string, string> = {};
  for (const side of ["top", "bottom", "left", "right"] as const) {
    vars[`--tg-safe-area-inset-${side}`] = `${safe[side]}px`;
    vars[`--tg-content-safe-area-inset-${side}`] = `${content[side]}px`;
  }
  return vars;
}

// ---------- счётчик владельцев флага (подтверждение закрытия) ----------

export type ToggleAdapter = { enable: () => void; disable: () => void };

/**
 * Флаг «включено, пока есть хотя бы один владелец»: два экрана (например, интервальная и силовая
 * живая сессия во время перехода) не отключают подтверждение друг другу. Адаптер дёргается только
 * при смене итогового состояния.
 */
export function createOwnerToggle(adapter: ToggleAdapter) {
  const owners = new Set<symbol>();
  let applied = false;
  function sync() {
    const wanted = owners.size > 0;
    if (wanted === applied) {
      return;
    }
    applied = wanted;
    if (wanted) {
      adapter.enable();
    } else {
      adapter.disable();
    }
  }
  return {
    acquire(): () => void {
      const owner = Symbol("owner");
      owners.add(owner);
      sync();
      return () => {
        owners.delete(owner);
        sync();
      };
    },
    isActive: () => applied,
  };
}

const closingConfirmation = createOwnerToggle({
  enable: () => {
    const webApp = getWebApp();
    if (isVersionAtLeast(webApp, MIN_VERSION.closingConfirmation) && typeof webApp?.enableClosingConfirmation === "function") {
      webApp.enableClosingConfirmation();
    }
  },
  disable: () => {
    const webApp = getWebApp();
    if (isVersionAtLeast(webApp, MIN_VERSION.closingConfirmation) && typeof webApp?.disableClosingConfirmation === "function") {
      webApp.disableClosingConfirmation();
    }
  },
});

/** Включить системное «Закрыть приложение?» (Bot API 6.2+), пока активна живая тренировка. Возвращает отмену. */
export function acquireClosingConfirmation(): () => void {
  return closingConfirmation.acquire();
}

// ---------- запуск ----------

function applyInsets(webApp: WebAppApi): void {
  if (typeof document === "undefined" || !isVersionAtLeast(webApp, MIN_VERSION.safeArea)) {
    return;
  }
  const vars = insetCssVars(normalizeInsets(webApp.safeAreaInset), normalizeInsets(webApp.contentSafeAreaInset));
  const root = document.documentElement.style;
  for (const [name, value] of Object.entries(vars)) {
    root.setProperty(name, value);
  }
}

/**
 * Один раз при старте (main.tsx, после init() SDK): ready → expand → запрет свайпа вниз → отступы.
 *  - ready(): Telegram убирает собственный лоадер (без него на части клиентов он висит поверх UI).
 *  - expand(): шторка Mini App на всю высоту (на iOS открывается наполовину).
 *  - disableVerticalSwipes() (7.7+): прокрутка вверх/вниз внутри приложения не сворачивает шторку
 *    посреди тренировки (закрытие по кнопке «Закрыть»/системное — как раньше).
 *  - safeAreaInset/contentSafeAreaInset (8.0+): CSS-переменные для полноэкранного режима.
 * Возвращает отписку от событий (для тестов).
 */
export function initTelegramPlatform(): () => void {
  const webApp = getWebApp();
  if (!webApp) {
    return () => {};
  }
  try {
    webApp.ready?.();
    webApp.expand?.();
    if (isVersionAtLeast(webApp, MIN_VERSION.disableVerticalSwipes)) {
      webApp.disableVerticalSwipes?.();
    }
  } catch (error) {
    console.error("Telegram platform init failed", error);
  }
  const refresh = () => applyInsets(webApp);
  refresh();
  const events = ["safeAreaChanged", "contentSafeAreaChanged", "fullscreenChanged"];
  for (const event of events) {
    webApp.onEvent?.(event, refresh);
  }
  return () => {
    for (const event of events) {
      webApp.offEvent?.(event, refresh);
    }
  };
}

/**
 * Закрыть экранную клавиатуру: у iOS-панели inputMode="decimal" нет клавиши Return/«Готово», так что
 * без явного blur клавиатура остаётся поверх «Записать подход» и следующих экранов (#224, п.7).
 */
export function dismissKeyboard(): void {
  if (typeof document === "undefined") {
    return;
  }
  const active = document.activeElement;
  if (active instanceof HTMLElement && active.matches("input, textarea, select")) {
    active.blur();
  }
}
