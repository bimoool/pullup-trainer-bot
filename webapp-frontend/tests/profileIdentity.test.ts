import assert from "node:assert/strict";
import { test } from "node:test";

import { avatarInitial, formatAge, identitySubtitle, telegramFirstName } from "../src/profileIdentity.ts";

const initData = (user: unknown) => `query_id=AAA&user=${encodeURIComponent(JSON.stringify(user))}&auth_date=1&hash=abc`;

test("telegramFirstName: имя из initData, пусто при отсутствии/ошибке", () => {
  assert.equal(telegramFirstName(initData({ id: 1, first_name: " Кирилл " })), "Кирилл");
  assert.equal(telegramFirstName(initData({ id: 1 })), "");
  assert.equal(telegramFirstName("auth_date=1"), "");
  assert.equal(telegramFirstName("user=%7Bbroken"), "");
  assert.equal(telegramFirstName(""), "");
});

test("formatAge: склонение год/года/лет", () => {
  assert.deepEqual([1, 2, 5, 11, 21, 31, 44, 112].map(formatAge), ["1 год", "2 года", "5 лет", "11 лет", "21 год", "31 год", "44 года", "112 лет"]);
});

test("identitySubtitle: пол и возраст, неизвестное опускается", () => {
  assert.equal(identitySubtitle("мужской", 31), "мужской · 31 год");
  assert.equal(identitySubtitle(null, 22), "22 года");
  assert.equal(identitySubtitle("женский", null), "женский");
  assert.equal(identitySubtitle(null, null), "");
});

test("avatarInitial: заглавная буква или пусто", () => {
  assert.equal(avatarInitial("кирилл"), "К");
  assert.equal(avatarInitial("  Anna"), "A");
  assert.equal(avatarInitial("🔥"), "");
  assert.equal(avatarInitial(""), "");
});
