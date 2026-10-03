import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { applyTelegramChrome, cssColorToHex, pickHeaderColorKey, resetTelegramChromeCache } from "../src/telegramChrome.ts";

type G = { window?: unknown; document?: unknown; getComputedStyle?: unknown };
const g = globalThis as unknown as G;

afterEach(() => {
  delete g.window;
  delete g.document;
  delete g.getComputedStyle;
  resetTelegramChromeCache();
});

test("cssColorToHex: hex, rgb, rgba(1), color(srgb); полупрозрачные — null", () => {
  assert.equal(cssColorToHex("#F2F2F7"), "#f2f2f7");
  assert.equal(cssColorToHex(" #fff "), "#ffffff");
  assert.equal(cssColorToHex("rgb(242, 242, 247)"), "#f2f2f7");
  assert.equal(cssColorToHex("rgba(23, 33, 43, 1)"), "#17212b");
  assert.equal(cssColorToHex("rgb(23 33 43 / 100%)"), "#17212b");
  assert.equal(cssColorToHex("color(srgb 1 1 1)"), "#ffffff");
  assert.equal(cssColorToHex("rgba(0, 0, 0, 0.5)"), null);
  assert.equal(cssColorToHex("transparent"), null);
  assert.equal(cssColorToHex(""), null);
});

test("pickHeaderColorKey: до 6.9 — ключ темы, ближайший к фону страницы", () => {
  assert.equal(pickHeaderColorKey("#f2f2f7", { secondary_bg_color: "#F2F2F7", bg_color: "#ffffff" }), "secondary_bg_color");
  assert.equal(pickHeaderColorKey("#17212b", { secondary_bg_color: "#232e3c" }), "bg_color");
  assert.equal(pickHeaderColorKey("#ffffff", undefined), "bg_color");
});

function stubEnv(version: string, tokens: Record<string, string>) {
  const calls: string[] = [];
  g.document = { documentElement: {} };
  g.getComputedStyle = () => ({ getPropertyValue: (name: string) => tokens[name] ?? "" });
  g.window = {
    Telegram: {
      WebApp: {
        version,
        themeParams: { secondary_bg_color: "#f2f2f7" },
        setHeaderColor: (c: string) => calls.push(`header:${c}`),
        setBackgroundColor: (c: string) => calls.push(`bg:${c}`),
        setBottomBarColor: (c: string) => calls.push(`bottom:${c}`),
      },
    },
  };
  return calls;
}

test("applyTelegramChrome 7.10: шапка и фон = фон страницы, нижняя панель = поверхность карточек", () => {
  const calls = stubEnv("7.10", { "--vp-page-bg": "#f2f2f7", "--vp-card-bg": "#ffffff" });
  applyTelegramChrome();
  assert.deepEqual(calls, ["header:#f2f2f7", "bg:#f2f2f7", "bottom:#ffffff"]);
  applyTelegramChrome(); // без смены токенов — повторно не дёргаем клиент
  assert.equal(calls.length, 3);
});

test("applyTelegramChrome 6.x: до 6.9 шапка — ключом темы, setBottomBarColor не вызывается", () => {
  const calls = stubEnv("6.4", { "--vp-page-bg": "#f2f2f7", "--vp-card-bg": "#ffffff" });
  applyTelegramChrome();
  assert.deepEqual(calls, ["header:secondary_bg_color", "bg:#f2f2f7"]);
});

test("applyTelegramChrome 6.0 и вне Telegram: ничего не вызывает", () => {
  const calls = stubEnv("6.0", { "--vp-page-bg": "#ffffff" });
  applyTelegramChrome();
  assert.deepEqual(calls, []);
  delete g.window;
  assert.doesNotThrow(() => applyTelegramChrome());
});

test("applyTelegramChrome: смена темы → новые цвета", () => {
  const tokens: Record<string, string> = { "--vp-page-bg": "#f2f2f7", "--vp-card-bg": "#ffffff" };
  const calls = stubEnv("8.0", tokens);
  applyTelegramChrome();
  tokens["--vp-page-bg"] = "#17212b";
  tokens["--vp-card-bg"] = "#232e3c";
  applyTelegramChrome();
  assert.deepEqual(calls.slice(3), ["header:#17212b", "bg:#17212b", "bottom:#232e3c"]);
});
