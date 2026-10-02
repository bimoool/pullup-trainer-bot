import assert from "node:assert/strict";
import test from "node:test";

import { classifyActiveConflict } from "../src/sessionConflict.ts";

const finish = { abandoned: false };

test("активная сессия с поставленным в очередь завершением — finish_pending", () => {
  assert.equal(classifyActiveConflict(7, { serverSessionId: 7, completeRequested: finish }), "finish_pending");
});

test("завершение чужой (другой) сессии не мешает продолжить текущую", () => {
  assert.equal(classifyActiveConflict(8, { serverSessionId: 7, completeRequested: finish }), "continue");
});

test("черновик без запрошенного завершения или пустая очередь — continue", () => {
  assert.equal(classifyActiveConflict(7, { serverSessionId: 7, completeRequested: null }), "continue");
  assert.equal(classifyActiveConflict(7, null), "continue");
});
