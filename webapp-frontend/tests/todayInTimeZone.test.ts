import assert from "node:assert/strict";
import { test } from "node:test";

import { noonInTimeZoneIso, todayInTimeZone } from "../src/todayInTimeZone.ts";

// Устройство UTC+5 (Екатеринбург) в 00:30 понедельника 2026-10-05 = 19:30 UTC воскресенья 2026-10-04 = 22:30 Москва 04.10.
const DEVICE_AHEAD = new Date("2026-10-04T19:30:00Z");

test("todayInTimeZone: профиль Москва отстаёт от устройства UTC+5 около полуночи", () => {
  assert.equal(todayInTimeZone("Europe/Moscow", DEVICE_AHEAD), "2026-10-04");
  assert.equal(todayInTimeZone("Asia/Yekaterinburg", DEVICE_AHEAD), "2026-10-05");
});

test("todayInTimeZone: профиль впереди устройства (UTC-10 устройство, Москва профиль)", () => {
  // 2026-10-04 23:30 UTC-10 = 2026-10-05 09:30 UTC = 12:30 Москва 05.10; Гонолулу всё ещё 04.10.
  const now = new Date("2026-10-05T09:30:00Z");
  assert.equal(todayInTimeZone("Pacific/Honolulu", now), "2026-10-04");
  assert.equal(todayInTimeZone("Europe/Moscow", now), "2026-10-05");
});

test("todayInTimeZone: граница суток ровно в полночь по поясу", () => {
  assert.equal(todayInTimeZone("Europe/Moscow", new Date("2026-10-04T20:59:59Z")), "2026-10-04");
  assert.equal(todayInTimeZone("Europe/Moscow", new Date("2026-10-04T21:00:00Z")), "2026-10-05");
});

test("todayInTimeZone: зона без перехода на летнее время и с переходом", () => {
  assert.equal(todayInTimeZone("Asia/Kolkata", new Date("2026-10-04T19:00:00Z")), "2026-10-05");
  assert.equal(todayInTimeZone("America/New_York", new Date("2026-03-08T06:59:00Z")), "2026-03-08");
});

test("todayInTimeZone: неизвестный/пустой пояс — день устройства", () => {
  const now = new Date(2026, 9, 4, 23, 30);
  assert.equal(todayInTimeZone(undefined, now), "2026-10-04");
  assert.equal(todayInTimeZone(null, now), "2026-10-04");
  assert.equal(todayInTimeZone("", now), "2026-10-04");
  assert.equal(todayInTimeZone("Not/AZone", now), "2026-10-04");
});

test("noonInTimeZoneIso: полдень выбранного дня в поясе профиля", () => {
  assert.equal(noonInTimeZoneIso("2026-10-04", "Europe/Moscow"), "2026-10-04T09:00:00.000Z");
  assert.equal(noonInTimeZoneIso("2026-10-04", "Pacific/Honolulu"), "2026-10-04T22:00:00.000Z");
  assert.equal(noonInTimeZoneIso("2026-10-04", "Asia/Kolkata"), "2026-10-04T06:30:00.000Z");
});

test("noonInTimeZoneIso: прошлый день не в будущем относительно «сейчас» в профиле", () => {
  const noon = new Date(noonInTimeZoneIso("2026-10-03", "Europe/Moscow"));
  assert.ok(noon.getTime() < DEVICE_AHEAD.getTime());
});
