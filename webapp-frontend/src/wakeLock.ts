/**
 * Wake Lock на время активной сессии (issue #186, раздел 10.8 docs/plan-and-specs.md:
 * "Wake Lock через nosleep.js включён на всё время сессии"). NoSleep.js — не
 * самописная обёртка над Screen Wake Lock API: сам определяет поддержку нативного
 * API и откатывается на видео-трюк там, где его нет (iOS Safari) — то, ради чего
 * его и взяли вместо голого `navigator.wakeLock`.
 *
 * Модуль держит один общий экземпляр NoSleep на вкладку (не по экрану) — второй
 * `enable()` на уже включённом сне — no-op в самой библиотеке, но общий модуль
 * избавляет вызывающий код от необходимости думать об этом.
 */
import NoSleep from "nosleep.js";

let noSleep: NoSleep | null = null;

export function enableWakeLock(): void {
  if (noSleep === null) {
    noSleep = new NoSleep();
  }
  void noSleep.enable();
}

export function disableWakeLock(): void {
  noSleep?.disable();
}
