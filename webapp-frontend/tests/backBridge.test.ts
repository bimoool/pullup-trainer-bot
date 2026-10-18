import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import { createBackButtonStack } from "../src/backButtonStack.ts";
import {
  adjustOverlayCount, browserBackAdapter, handleEscape, resetBackBridgeForTests, triggerBack,
} from "../src/platform/backStore.ts";

beforeEach(() => resetBackBridgeForTests());

const esc = { key: "Escape", defaultPrevented: false, isComposing: false };

function setup() {
  const stack = createBackButtonStack({ available: () => true, ...browserBackAdapter }, (task) => task());
  return stack;
}

test("браузерный мост: клик получает только верхний обработчик стека", () => {
  const stack = setup();
  const log: string[] = [];
  const popParent = stack.push(() => () => log.push("parent"));
  const popChild = stack.push(() => () => log.push("child"));
  triggerBack();
  assert.deepEqual(log, ["child"]);
  popChild();
  triggerBack();
  assert.deepEqual(log, ["child", "parent"]);
  popParent();
});

test("Escape срабатывает только при открытой шторке", () => {
  const stack = setup();
  let closed = 0;
  stack.push(() => () => { closed += 1; });
  assert.equal(handleEscape(esc), false);
  adjustOverlayCount(1);
  assert.equal(handleEscape(esc), true);
  assert.equal(closed, 1);
  assert.equal(handleEscape({ ...esc, key: "Enter" }), false);
  assert.equal(handleEscape({ ...esc, isComposing: true }), false);
  adjustOverlayCount(-1);
  assert.equal(handleEscape(esc), false);
});
