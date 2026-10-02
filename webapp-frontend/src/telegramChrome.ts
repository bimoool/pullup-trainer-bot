// Цвета «хрома» Telegram вокруг Mini App (#224): шапка клиента, фон за страницей (виден при
// перетягивании у iOS), нижняя панель. Без этого шапка остаётся цвета темы клиента, а наша страница —
// серая (светлая тема, shell.css: --vp-page-bg = secondary), и на стыке видна полоса другого цвета.
//
// applyTelegramChrome() — идемпотентна и безопасна вне Telegram; её нужно вызывать после любой
// смены темы: при старте (initTelegramChrome ниже), при смене настройки темы Mini App (подписка на
// displayPrefs) и из слушателя themeChanged (main.tsx, ветка live-ux-fixes) — см. отчёт #224.
import { getWebApp, isVersionAtLeast, MIN_VERSION } from "./telegramPlatform.ts";

/** Разбор вычисленного CSS-цвета → "#rrggbb"; null, если формат не распознан или цвет полупрозрачный. */
export function cssColorToHex(css: string): string | null {
  const value = css.trim().toLowerCase();
  const hex6 = /^#([0-9a-f]{6})$/.exec(value);
  if (hex6) {
    return `#${hex6[1]}`;
  }
  const hex3 = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/.exec(value);
  if (hex3) {
    return `#${hex3[1]}${hex3[1]}${hex3[2]}${hex3[2]}${hex3[3]}${hex3[3]}`;
  }
  const rgb = /^rgba?\(\s*(\d+(?:\.\d+)?)[\s,]+(\d+(?:\.\d+)?)[\s,]+(\d+(?:\.\d+)?)(?:\s*[,/]\s*(\d+(?:\.\d+)?%?))?\s*\)$/.exec(value);
  if (rgb) {
    const alpha = rgb[4] === undefined ? 1 : rgb[4].endsWith("%") ? Number(rgb[4].slice(0, -1)) / 100 : Number(rgb[4]);
    if (alpha < 1) {
      return null;
    }
    return toHex([Number(rgb[1]), Number(rgb[2]), Number(rgb[3])]);
  }
  const srgb = /^color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+))?\)$/.exec(value);
  if (srgb) {
    if (srgb[4] !== undefined && Number(srgb[4]) < 1) {
      return null;
    }
    return toHex([Number(srgb[1]) * 255, Number(srgb[2]) * 255, Number(srgb[3]) * 255]);
  }
  return null;
}

function toHex(channels: number[]): string {
  return `#${channels.map((channel) => Math.max(0, Math.min(255, Math.round(channel))).toString(16).padStart(2, "0")).join("")}`;
}

/**
 * До Bot API 6.9 setHeaderColor принимает только ключ темы, не hex. Подбираем ближайший: если наш
 * фон страницы совпал с secondary_bg_color клиента — берём его, иначе bg_color.
 */
export function pickHeaderColorKey(pageHex: string, themeParams: Record<string, string> | undefined): "bg_color" | "secondary_bg_color" {
  const secondary = themeParams?.secondary_bg_color?.toLowerCase();
  return secondary !== undefined && secondary === pageHex.toLowerCase() ? "secondary_bg_color" : "bg_color";
}

export type ChromeColors = { header: string; background: string; bottomBar: string };

let lastApplied: string | null = null;

/** Применяет цвета шапки / фона / нижней панели Telegram по токенам оболочки (--vp-page-bg / --vp-card-bg). */
export function applyTelegramChrome(): void {
  const webApp = getWebApp();
  if (!webApp || typeof document === "undefined") {
    return;
  }
  const styles = getComputedStyle(document.documentElement);
  const page = cssColorToHex(styles.getPropertyValue("--vp-page-bg"));
  const card = cssColorToHex(styles.getPropertyValue("--vp-card-bg"));
  if (page === null) {
    return;
  }
  const bottom = card ?? page;
  const signature = `${page}|${bottom}|${webApp.version ?? ""}`;
  if (signature === lastApplied) {
    return;
  }
  lastApplied = signature;
  try {
    if (isVersionAtLeast(webApp, MIN_VERSION.setColors)) {
      const header = isVersionAtLeast(webApp, MIN_VERSION.headerColorHex) ? page : pickHeaderColorKey(page, webApp.themeParams);
      webApp.setHeaderColor?.(header);
      webApp.setBackgroundColor?.(page);
    }
    if (isVersionAtLeast(webApp, MIN_VERSION.setBottomBarColor)) {
      webApp.setBottomBarColor?.(bottom);
    }
  } catch (error) {
    console.error("applyTelegramChrome failed", error);
  }
}

/** Сбросить кэш последнего применения (для тестов / принудительной перерисовки). */
export function resetTelegramChromeCache(): void {
  lastApplied = null;
}
