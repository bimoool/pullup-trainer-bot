/**
 * Wake Lock на время активной сессии (issue #186, раздел 10.8 docs/plan-and-specs.md;
 * #269 — повторный захват после возврата из фона).
 *
 * Браузер САМ снимает Screen Wake Lock, когда вкладка/WebView уходит в фон (экран
 * заблокирован, Telegram свёрнут), — поэтому одного `enable()` при монтировании мало:
 * пока сессия жива (`active`), на `visibilitychange → visible` замок берётся заново.
 * Где есть нативный `navigator.wakeLock` — работаем с ним напрямую (один собственный
 * sentinel, без двойных запросов и «утёкших» замков, которые не снимет `disable()`);
 * где его нет (iOS Safari) — откат на NoSleep.js (видео-трюк).
 *
 * Один общий экземпляр на вкладку: повторный `enable()` — no-op.
 */
import NoSleep from "nosleep.js";

type Sentinel = EventTarget & { release: () => Promise<void> };

let noSleep: NoSleep | null = null;
let sentinel: Sentinel | null = null;
let active = false;
let listening = false;

function hasNativeWakeLock(): boolean {
  return typeof navigator !== "undefined" && "wakeLock" in navigator;
}

async function acquire(): Promise<void> {
  if (!active) {
    return;
  }
  if (hasNativeWakeLock()) {
    if (sentinel !== null) {
      return; // уже держим живой замок
    }
    try {
      const lock = (await navigator.wakeLock.request("screen")) as Sentinel;
      if (!active || sentinel !== null) {
        void lock.release(); // сессию закрыли (или замок уже взят), пока запрос был в полёте
        return;
      }
      sentinel = lock;
      lock.addEventListener("release", () => {
        if (sentinel === lock) {
          sentinel = null; // снят браузером (фон) — handleVisibility возьмёт заново
        }
      });
    } catch (error) {
      console.error(`Wake Lock: ${error instanceof Error ? error.message : String(error)}`);
    }
    return;
  }
  if (noSleep === null) {
    noSleep = new NoSleep();
  }
  try {
    await noSleep.enable();
  } catch (error) {
    console.error(`Wake Lock: ${error instanceof Error ? error.message : String(error)}`);
  }
}

function handleVisibility(): void {
  if (document.visibilityState === "visible") {
    void acquire();
  }
}

export function enableWakeLock(): void {
  active = true;
  if (!listening) {
    document.addEventListener("visibilitychange", handleVisibility);
    listening = true;
  }
  void acquire();
}

export function disableWakeLock(): void {
  active = false;
  if (listening) {
    document.removeEventListener("visibilitychange", handleVisibility);
    listening = false;
  }
  if (sentinel !== null) {
    void sentinel.release();
    sentinel = null;
  }
  noSleep?.disable();
}
