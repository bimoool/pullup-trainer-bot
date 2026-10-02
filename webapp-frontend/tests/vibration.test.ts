import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { isVibrationEnabled, setVibrationEnabled, vibratePhaseEnd, vibrationDelayMs } from "../src/vibration.ts";

type G = { window?: unknown };
const g = globalThis as unknown as G;

function stubWindow(haptic?: { notificationOccurred: (t: string) => void }) {
  const store = new Map<string, string>();
  g.window = {
    localStorage: { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) },
    Telegram: haptic ? { WebApp: { HapticFeedback: haptic } } : undefined,
  };
}

afterEach(() => {
  delete g.window;
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
