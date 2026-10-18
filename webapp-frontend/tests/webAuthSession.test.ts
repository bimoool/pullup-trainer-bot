import assert from "node:assert/strict";
import { test } from "node:test";

import { clearLocalUserData } from "../src/platform/session.ts";

test("clearLocalUserData: удаляет кэш запросов предыдущего пользователя", () => {
  const removed: string[] = [];
  clearLocalUserData({ removeItem: (key: string) => void removed.push(key) });
  assert.deepEqual(removed, ["pullup-v2-query-cache"]);
});

test("clearLocalUserData: недоступное хранилище не роняет выход", () => {
  assert.doesNotThrow(() => clearLocalUserData({ removeItem: () => { throw new Error("denied"); } }));
  assert.doesNotThrow(() => clearLocalUserData(undefined));
});
