import assert from "node:assert/strict";
import { test } from "node:test";

import { FIELD_BLUR_GRACE_MS, isTextEntryTarget } from "../src/liveFieldFocus.ts";

test("isTextEntryTarget: поля, открывающие клавиатуру", () => {
  assert.equal(isTextEntryTarget({ tagName: "INPUT", type: "number" }), true);
  assert.equal(isTextEntryTarget({ tagName: "input", type: "text" }), true);
  assert.equal(isTextEntryTarget({ tagName: "INPUT" }), true);
  assert.equal(isTextEntryTarget({ tagName: "TEXTAREA" }), true);
});

test("isTextEntryTarget: кнопки, чекбоксы и не-поля — нет", () => {
  assert.equal(isTextEntryTarget({ tagName: "BUTTON" }), false);
  assert.equal(isTextEntryTarget({ tagName: "INPUT", type: "checkbox" }), false);
  assert.equal(isTextEntryTarget({ tagName: "INPUT", type: "submit" }), false);
  assert.equal(isTextEntryTarget({ tagName: "DIV" }), false);
  assert.equal(isTextEntryTarget(null), false);
  assert.equal(isTextEntryTarget(undefined), false);
});

test("FIELD_BLUR_GRACE_MS: достаточно для тапа по кнопке транспорта", () => {
  assert.ok(FIELD_BLUR_GRACE_MS >= 200 && FIELD_BLUR_GRACE_MS <= 1000);
});
