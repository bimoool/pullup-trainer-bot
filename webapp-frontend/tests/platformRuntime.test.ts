import assert from "node:assert/strict";
import { test } from "node:test";

import { detectBrowserRuntime } from "../src/platform/runtime.ts";
import { answerConfirm, currentConfirm, requestConfirm } from "../src/platform/confirmStore.ts";

test("обычный браузер: WebApp без initData и platform unknown -> браузер", () => {
  assert.equal(detectBrowserRuntime({ initData: "", platform: "unknown" }, { hash: "", search: "" }), true);
  assert.equal(detectBrowserRuntime(undefined, { hash: "#/x", search: "?a=1" }), true);
  assert.equal(detectBrowserRuntime(null, null), true);
});

test("Telegram: любой из признаков (initData, платформа, launch params в URL)", () => {
  assert.equal(detectBrowserRuntime({ initData: "query_id=1", platform: "unknown" }, {}), false);
  assert.equal(detectBrowserRuntime({ initData: "", platform: "tdesktop" }, {}), false);
  assert.equal(detectBrowserRuntime({ version: "7.0" } as never, {}), false); // нестандартный мост без platform
  assert.equal(detectBrowserRuntime(undefined, { hash: "#tgWebAppData=abc&tgWebAppVersion=7.0" }), false);
  assert.equal(detectBrowserRuntime({ initData: "" }, { search: "?tgWebAppPlatform=ios" }), false);
});

test("confirmStore: очередь запросов отвечает по порядку", async () => {
  const first = requestConfirm("первый");
  const second = requestConfirm("второй");
  assert.equal(currentConfirm()?.message, "первый");
  answerConfirm(true);
  assert.equal(await first, true);
  assert.equal(currentConfirm()?.message, "второй");
  answerConfirm(false);
  assert.equal(await second, false);
  assert.equal(currentConfirm(), null);
  answerConfirm(true); // пустая очередь — не падает
});
