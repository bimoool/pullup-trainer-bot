import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { isVibrationEnabled, setVibrationEnabled, vibratePhaseEnd, vibrationDelayMs } from "../src/vibration.ts";

type G = { window?: unknown };
const g = globalThis as unknown as G;

function stubWindow(haptic?: { notificationOccurred: (t: string) => void }, isVersionAtLeast?: (v: string) => boolean) {
  const store = new Map<string, string>();
  g.window = {
    localStorage: { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) },
    Telegram: haptic ? { WebApp: { HapticFeedback: haptic, isVersionAtLeast } } : undefined,
  };
}

afterEach(() => {
  delete g.window;
  delete (globalThis as { navigator?: unknown }).navigator;
});

test("вибрация включена по умолчанию, выключатель сохраняется", () => {
  stubWindow();
  assert.equal(isVibrationEnabled(), true);
  setVibrationEnabled(false);
  assert.equal(isVibrationEnabled(), false);
  setVibrationEnabled(true);
  assert.equal(isVibrationEnabled(), true);
});

test("vibratePhaseEnd: Telegram HapticFeedback success; при выключении — тишина", () => {
  const calls: string[] = [];
  stubWindow({ notificationOccurred: (type) => calls.push(type) });
  assert.equal(vibratePhaseEnd(), true);
  assert.deepEqual(calls, ["success"]);
  setVibrationEnabled(false);
  assert.equal(vibratePhaseEnd(), false);
  assert.deepEqual(calls, ["success"]);
});

test("vibrationDelayMs: истёкшая фаза — null (без опоздавшего сигнала)", () => {
  assert.equal(vibrationDelayMs(10_000, 4_000), 6_000);
  assert.equal(vibrationDelayMs(4_000, 4_000), null);
  assert.equal(vibrationDelayMs(3_000, 4_000), null);
});

test("vibratePhaseEnd: Telegram < 6.1 — HapticFeedback пустышка, идём в navigator.vibrate (#284 C2)", () => {
  const calls: string[] = [];
  const vibrated: number[] = [];
  stubWindow({ notificationOccurred: (type) => calls.push(type) }, (v) => v !== "6.1");
  Object.defineProperty(globalThis, "navigator", {
    value: { vibrate: (ms: number) => (vibrated.push(ms), true) }, configurable: true,
  });
  assert.equal(vibratePhaseEnd(), true);
  assert.deepEqual(calls, []);
  assert.deepEqual(vibrated, [200]);
});

test("vibratePhaseEnd: Telegram >= 6.1 — HapticFeedback, vibrate не нужен; без isVersionAtLeast — как раньше", () => {
  const calls: string[] = [];
  stubWindow({ notificationOccurred: (type) => calls.push(type) }, () => true);
  assert.equal(vibratePhaseEnd(), true);
  assert.deepEqual(calls, ["success"]);
  stubWindow({ notificationOccurred: (type) => calls.push(type) }); // isVersionAtLeast отсутствует
  assert.equal(vibratePhaseEnd(), true);
  assert.deepEqual(calls, ["success", "success"]);
});
