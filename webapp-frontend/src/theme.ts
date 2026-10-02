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
