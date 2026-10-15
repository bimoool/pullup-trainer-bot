import assert from "node:assert/strict";
import { test } from "node:test";

import { autosavedEditMessage, pendingCorrection } from "../src/liveEditDraft.ts";

const target = { block_index: 0, set_index: 0, round_index: null, value: 6 };

test("pendingCorrection: изменённое число в черновике сохраняется в тот подход, который правили (H2)", () => {
  assert.deepEqual(pendingCorrection(target, "4"), { block_index: 0, set_index: 0, round_index: null, value: 4 });
  assert.deepEqual(pendingCorrection({ ...target, set_index: 2, round_index: 1 }, "7.5"), {
    block_index: 0, set_index: 2, round_index: 1, value: 7.5,
  });
});

test("pendingCorrection: нечего сохранять — без изменений, пустое/неполное поле, нет цели", () => {
  assert.equal(pendingCorrection(target, "6"), null);
  assert.equal(pendingCorrection(target, ""), null);
  assert.equal(pendingCorrection(target, "."), null);
  assert.equal(pendingCorrection(null, "4"), null);
});

test("autosavedEditMessage: номер подхода с единицы", () => {
  assert.equal(autosavedEditMessage(target, 4), "Подход 1 исправлен: 4");
});
