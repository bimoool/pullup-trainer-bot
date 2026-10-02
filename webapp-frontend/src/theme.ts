// Тема Mini App (#268): «Как в Telegram» (auto) / «Светлая» / «Тёмная». Чистая часть —
// палитры и выбор appearance; DOM-часть (setProperty) вызывается из main.tsx.

export type ThemePref = "auto" | "light" | "dark";

/** CSS-переменные, которые main.tsx перекрывает из themeParams (--tg-* наши, --tg-theme-* для tgui). */
export const THEME_VARS = [
  "bg-color",
  "text-color",
  "hint-color",
  "link-color",
  "button-color",
  "button-text-color",
  "secondary-bg-color",
  "section-bg-color",
  "subtitle-text-color",
  "destructive-text-color",
] as const;

export const PALETTES: Record<"light" | "dark", Record<(typeof THEME_VARS)[number], string>> = {
  light: {
    "bg-color": "#ffffff",
    "text-color": "#111111",
    "hint-color": "#999999",
    "link-color": "#2481cc",
    "button-color": "#2481cc",
    "button-text-color": "#ffffff",
    "secondary-bg-color": "#f2f2f7",
    "section-bg-color": "#ffffff",
    "subtitle-text-color": "#707579",
    "destructive-text-color": "#e53935",
  },
  dark: {
    "bg-color": "#17212b",
    "text-color": "#f5f5f5",
    "hint-color": "#708499",
    "link-color": "#6ab3f3",
    "button-color": "#5288c1",
    "button-text-color": "#ffffff",
    "secondary-bg-color": "#232e3c",
    "section-bg-color": "#17212b",
    "subtitle-text-color": "#708499",
    "destructive-text-color": "#ec3942",
  },
};

export const THEME_LABEL: Record<ThemePref, string> = {
  auto: "Как в Telegram",
  light: "Светлая",
  dark: "Тёмная",
};

export function isThemePref(value: unknown): value is ThemePref {
  return value === "auto" || value === "light" || value === "dark";
}

/** appearance для AppRoot: override побеждает, auto — схема Telegram (или undefined → media query). */
export function resolveAppearance(pref: ThemePref, telegramScheme: "light" | "dark" | undefined): "light" | "dark" | undefined {
  return pref === "auto" ? telegramScheme : pref;
}

/** Схема, о которой сообщает Telegram (`WebApp.colorScheme`); всё остальное — undefined. */
export function readTelegramColorScheme(webApp: { colorScheme?: unknown } | null | undefined): "light" | "dark" | undefined {
  const scheme = webApp?.colorScheme;
  return scheme === "light" || scheme === "dark" ? scheme : undefined;
}

/** Тёмная ли поверхность по значению `--tg-bg-color` (#rrggbb): яркость < 0.5. Не #rrggbb → светлая. */
export function isDarkBackground(raw: string): boolean {
  const match = /^#([0-9a-f]{6})$/i.exec(raw.trim());
  if (!match) {
    return false;
  }
  const n = parseInt(match[1], 16);
  const luminance = (0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255;
  return luminance < 0.5;
}

// ---------- событие theme_changed по шине SDK (#287 MED 4) ----------
// На нативных iOS/Android клиентах init() @telegram-apps/sdk заменяет
// window.Telegram.WebView.receiveEvent своим (событие уходит только в шину SDK), поэтому
// WebApp.onEvent("themeChanged") из telegram-web-app.js не срабатывает, а WebApp.themeParams/
// colorScheme остаются старыми. Тема берётся из полезной нагрузки события.

/** theme_params из полезной нагрузки `theme_changed` ({ theme_params: { bg_color: "#…" } }); только строки. */
export function themeParamsFromEvent(payload: unknown): Record<string, string> | null {
  const raw = (payload as { theme_params?: unknown } | null | undefined)?.theme_params;
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    return null;
  }
  const params: Record<string, string> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof value === "string") {
      params[key] = value;
    }
  }
  return params;
}

/** Схема по bg_color — так же её выводит telegram-web-app.js; нет валидного bg_color — undefined. */
export function colorSchemeFromThemeParams(params: Record<string, string>): "light" | "dark" | undefined {
  const bg = params.bg_color?.trim() ?? "";
  if (!/^#[0-9a-f]{6}$/i.test(bg)) {
    return undefined;
  }
  return isDarkBackground(bg) ? "dark" : "light";
}

/** Отпечаток темы: один и тот же themeChanged, пришедший обоими путями (iframe-клиенты: и мост,
 * и шина SDK), применяется один раз. Порядок ключей и регистр значений не важны. */
export function themeSignature(params: Record<string, string> | null | undefined, scheme: string | undefined): string {
  const entries = Object.entries(params ?? {})
    .map(([key, value]) => [key, value.trim().toLowerCase()] as const)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return JSON.stringify([scheme ?? null, entries]);
}
