import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import {
  MIN_VERSION, acquireClosingConfirmation, compareVersions, createOwnerToggle, dismissKeyboard, effectiveInsetPx,
  initTelegramPlatform, insetCssVars, insetsFromEvent, isVersionAtLeast, normalizeInsets,
} from "../src/telegramPlatform.ts";

type G = { window?: unknown; document?: unknown };
const g = globalThis as unknown as G;

afterEach(() => {
  delete g.window;
  delete g.document;
});

test("compareVersions: числовое сравнение сегментов (7.10 > 7.9)", () => {
  assert.equal(compareVersions("7.10", "7.9"), 1);
  assert.equal(compareVersions("7.7", "7.7"), 0);
  assert.equal(compareVersions("6.9", "7.0"), -1);
  assert.equal(compareVersions("8", "8.0"), 0);
  assert.equal(compareVersions("8.0.1", "8.0"), 1);
});

test("isVersionAtLeast: версия клиента против порога, без версии — не поддерживается", () => {
  assert.equal(isVersionAtLeast({ version: "7.7" }, MIN_VERSION.disableVerticalSwipes), true);
  assert.equal(isVersionAtLeast({ version: "7.6" }, MIN_VERSION.disableVerticalSwipes), false);
  assert.equal(isVersionAtLeast({ version: "7.9" }, MIN_VERSION.setBottomBarColor), false);
  assert.equal(isVersionAtLeast({ version: "7.10" }, MIN_VERSION.setBottomBarColor), true);
  assert.equal(isVersionAtLeast({ version: "8.0" }, MIN_VERSION.safeArea), true);
  assert.equal(isVersionAtLeast(undefined, "6.1"), false);
  assert.equal(isVersionAtLeast({}, "6.1"), false);
  // нет строки версии, но есть isVersionAtLeast клиента
  assert.equal(isVersionAtLeast({ isVersionAtLeast: (v) => v === "6.2" }, "6.2"), true);
  assert.equal(isVersionAtLeast({ isVersionAtLeast: () => { throw new Error("x"); } }, "6.2"), false);
});

test("normalizeInsets: мусор и отрицательные значения → 0", () => {
  assert.deepEqual(normalizeInsets(undefined), { top: 0, bottom: 0, left: 0, right: 0 });
  assert.deepEqual(normalizeInsets({ top: 47, bottom: -3, left: Number.NaN }), { top: 47, bottom: 0, left: 0, right: 0 });
});

test("effectiveInsetPx: max(env, safe) + content", () => {
  assert.equal(effectiveInsetPx(0, 0, 0), 0);
  assert.equal(effectiveInsetPx(34, 34, 0), 34); // одно и то же железо не удваивается
  assert.equal(effectiveInsetPx(0, 59, 44), 103); // полноэкранный iOS: вырез + шапка Telegram
  assert.equal(effectiveInsetPx(20, 10, 5), 25);
  assert.equal(effectiveInsetPx(-5, Number.NaN, 12), 12);
});

test("insetCssVars: имена как у telegram-web-app.js, значения в px", () => {
  const vars = insetCssVars({ top: 59, bottom: 34, left: 0, right: 0 }, { top: 44, bottom: 0, left: 0, right: 0 });
  assert.equal(vars["--tg-safe-area-inset-top"], "59px");
  assert.equal(vars["--tg-safe-area-inset-bottom"], "34px");
  assert.equal(vars["--tg-content-safe-area-inset-top"], "44px");
  assert.equal(Object.keys(vars).length, 8);
});

test("createOwnerToggle: включено, пока есть хоть один владелец; адаптер — только на смене состояния", () => {
  const calls: string[] = [];
  const toggle = createOwnerToggle({ enable: () => calls.push("on"), disable: () => calls.push("off") });
  const releaseA = toggle.acquire();
  const releaseB = toggle.acquire();
  assert.deepEqual(calls, ["on"]);
  releaseA();
  assert.equal(toggle.isActive(), true);
  assert.deepEqual(calls, ["on"]);
  releaseB();
  assert.equal(toggle.isActive(), false);
  assert.deepEqual(calls, ["on", "off"]);
  releaseB(); // повторная отмена безвредна
  assert.deepEqual(calls, ["on", "off"]);
});

test("подтверждение закрытия: вызывается только с Bot API 6.2+", () => {
  const calls: string[] = [];
  const webApp = (version: string) => ({
    version,
    enableClosingConfirmation: () => calls.push("enable"),
    disableClosingConfirmation: () => calls.push("disable"),
  });
  g.window = { Telegram: { WebApp: webApp("6.1") } };
  acquireClosingConfirmation()();
  assert.deepEqual(calls, []);
  g.window = { Telegram: { WebApp: webApp("7.0") } };
  const release = acquireClosingConfirmation();
  assert.deepEqual(calls, ["enable"]);
  release();
  assert.deepEqual(calls, ["enable", "disable"]);
});

test("initTelegramPlatform: ready+expand всегда, disableVerticalSwipes только с 7.7; вне Telegram — no-op", () => {
  assert.doesNotThrow(() => initTelegramPlatform()());
  const calls: string[] = [];
  const make = (version: string) => ({
    version,
    ready: () => calls.push("ready"),
    expand: () => calls.push("expand"),
    disableVerticalSwipes: () => calls.push("noswipe"),
  });
  g.window = { Telegram: { WebApp: make("7.6") } };
  initTelegramPlatform();
  assert.deepEqual(calls, ["ready", "expand"]);
  calls.length = 0;
  g.window = { Telegram: { WebApp: make("7.7") } };
  initTelegramPlatform();
  assert.deepEqual(calls, ["ready", "expand", "noswipe"]);
});

test("initTelegramPlatform: отступы 8.0+ → CSS-переменные и подписка на события", () => {
  const style = new Map<string, string>();
  g.document = { documentElement: { style: { setProperty: (k: string, v: string) => style.set(k, v) } } };
  const handlers: Record<string, () => void> = {};
  const webApp = {
    version: "8.0",
    safeAreaInset: { top: 59, bottom: 34, left: 0, right: 0 } as { top: number; bottom: number; left: number; right: number },
    contentSafeAreaInset: { top: 44, bottom: 0, left: 0, right: 0 },
    onEvent: (name: string, handler: () => void) => { handlers[name] = handler; },
    offEvent: () => {},
  };
  g.window = { Telegram: { WebApp: webApp } };
  initTelegramPlatform();
  assert.equal(style.get("--tg-safe-area-inset-top"), "59px");
  assert.equal(style.get("--tg-content-safe-area-inset-top"), "44px");
  webApp.safeAreaInset = { top: 0, bottom: 0, left: 0, right: 0 };
  handlers.safeAreaChanged();
  assert.equal(style.get("--tg-safe-area-inset-top"), "0px");
  // 7.x: переменные не трогаем
  style.clear();
  g.window = { Telegram: { WebApp: { ...webApp, version: "7.10" } } };
  initTelegramPlatform();
  assert.equal(style.size, 0);
});

test("insetsFromEvent: полезная нагрузка safe_area_changed шины SDK", () => {
  assert.deepEqual(insetsFromEvent({ top: 59, bottom: 34, left: 0, right: 0 }), { top: 59, bottom: 34, left: 0, right: 0 });
  assert.deepEqual(insetsFromEvent({ top: -1 }), { top: 0, bottom: 0, left: 0, right: 0 });
  assert.equal(insetsFromEvent(null), null);
  assert.equal(insetsFromEvent("x"), null);
  assert.equal(insetsFromEvent([1, 2]), null);
});

test("initTelegramPlatform (#287 MED 4): нативный путь — инсеты из шины SDK при молчащем мосте; оба пути — одна запись", () => {
  const writes: string[] = [];
  const style = new Map<string, string>();
  g.document = { documentElement: { style: { setProperty: (k: string, v: string) => { writes.push(k); style.set(k, v); } } } };
  const bridge: Record<string, () => void> = {};
  const sdk: Record<string, (payload: unknown) => void> = {};
  const unsubscribed: string[] = [];
  const webApp = {
    version: "8.0",
    safeAreaInset: { top: 59, bottom: 34, left: 0, right: 0 },
    contentSafeAreaInset: { top: 44, bottom: 0, left: 0, right: 0 },
    onEvent: (name: string, handler: () => void) => { bridge[name] = handler; },
    offEvent: () => {},
  };
  g.window = { Telegram: { WebApp: webApp } };
  const stop = initTelegramPlatform((event, handler) => {
    sdk[event] = handler;
    return () => void unsubscribed.push(event);
  });
  assert.deepEqual(Object.keys(sdk).sort(), ["content_safe_area_changed", "fullscreen_changed", "safe_area_changed"]);

  // Нативный клиент: WebApp.safeAreaInset НЕ обновлён (мост молчит), инсеты — только в событии SDK.
  sdk.safe_area_changed({ top: 0, bottom: 0, left: 0, right: 0 });
  sdk.content_safe_area_changed({ top: 0, bottom: 0, left: 0, right: 0 });
  assert.equal(style.get("--tg-safe-area-inset-top"), "0px");
  assert.equal(style.get("--tg-safe-area-inset-bottom"), "0px");
  assert.equal(style.get("--tg-content-safe-area-inset-top"), "0px");

  // iframe-клиент: то же событие пришло и мостом (WebApp обновлён) — повторной записи нет.
  webApp.safeAreaInset = { top: 0, bottom: 0, left: 0, right: 0 };
  webApp.contentSafeAreaInset = { top: 0, bottom: 0, left: 0, right: 0 };
  writes.length = 0;
  bridge.safeAreaChanged();
  sdk.safe_area_changed({ top: 0, bottom: 0, left: 0, right: 0 });
  assert.deepEqual(writes, []);
  // мусорная нагрузка игнорируется
  sdk.safe_area_changed(null);
  assert.equal(style.get("--tg-safe-area-inset-top"), "0px");

  stop();
  assert.deepEqual(unsubscribed.sort(), ["content_safe_area_changed", "fullscreen_changed", "safe_area_changed"]);
});

test("dismissKeyboard: снимает фокус только с полей ввода", () => {
  class FakeEl {
    blurred = false;
    tag: string;
    constructor(tag: string) {
      this.tag = tag;
    }
    matches(selector: string) { return selector.split(",").map((s) => s.trim()).includes(this.tag); }
    blur() { this.blurred = true; }
  }
  (globalThis as unknown as { HTMLElement: unknown }).HTMLElement = FakeEl;
  const input = new FakeEl("input");
  g.document = { activeElement: input };
  dismissKeyboard();
  assert.equal(input.blurred, true);
  const button = new FakeEl("button");
  g.document = { activeElement: button };
  dismissKeyboard();
  assert.equal(button.blurred, false);
  delete (globalThis as unknown as { HTMLElement?: unknown }).HTMLElement;
});
