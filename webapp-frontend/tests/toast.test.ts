import assert from "node:assert/strict";
import { test } from "node:test";

import { createToastStore, TOAST_DURATION_MS } from "../src/toast.ts";

function manualClock() {
  const timers = new Map<number, () => void>();
  let next = 1;
  return {
    schedule: (fn: () => void, ms: number) => {
      assert.equal(ms, TOAST_DURATION_MS);
      const id = next++;
      timers.set(id, fn);
      return id;
    },
    cancel: (id: unknown) => {
      timers.delete(id as number);
    },
    fireAll: () => {
      const pending = [...timers.values()];
      timers.clear();
      pending.forEach((fn) => fn());
    },
    size: () => timers.size,
  };
}

test("toast: показывается, уведомляет подписчиков и исчезает по таймеру", () => {
  const clock = manualClock();
  const store = createToastStore(clock.schedule, clock.cancel);
  const seen: (string | null)[] = [];
  const off = store.subscribe((toast) => seen.push(toast?.text ?? null));
  store.show("Тренировка удалена");
  assert.equal(store.current()?.text, "Тренировка удалена");
  clock.fireAll();
  assert.equal(store.current(), null);
  assert.deepEqual(seen, ["Тренировка удалена", null]);
  off();
  store.show("ещё");
  assert.deepEqual(seen, ["Тренировка удалена", null]);
});

test("toast: новое сообщение заменяет предыдущее, старый таймер его не гасит", () => {
  const clock = manualClock();
  const store = createToastStore(clock.schedule, clock.cancel);
  store.show("Первое");
  store.show("Второе");
  assert.equal(clock.size(), 1);
  assert.equal(store.current()?.text, "Второе");
  clock.fireAll();
  assert.equal(store.current(), null);
});
