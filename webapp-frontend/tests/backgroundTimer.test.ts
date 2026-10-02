import assert from "node:assert/strict";
import { test } from "node:test";

import { computeIntervalState } from "../src/intervalTiming.ts";
import { phaseEndCueDelaySeconds } from "../src/phaseAudio.ts";

// #269 — фон/возврат: всё считается из абсолютных timestamps.

test("сигнал конца фазы: будущая фаза — задержка в секундах, истёкшая в фоне — null (без бипа)", () => {
  assert.equal(phaseEndCueDelaySeconds(70_000, 10_000), 60);
  assert.equal(phaseEndCueDelaySeconds(70_000, 70_000), null);
  assert.equal(phaseEndCueDelaySeconds(70_000, 130_000), null);
});

const interval = { totalDurationSeconds: 180, workSeconds: 10, restSeconds: 20 };

test("interval: возврат из фона через 25 с — та же фаза и раунд, что и при непрерывном тике", () => {
  const start = 1_000_000;
  const back = computeIntervalState({ executionStartedAtMs: start, nowMs: start + 25_000, ...interval });
  // 0-10 work, 10-30 rest → через 25 с идёт отдых, остаток 5 с
  assert.equal(back.phase, "rest");
  assert.equal(Math.round(back.remainingInPhaseSeconds), 5);
  assert.equal(back.completedCycles, 1);
  // тик «на границе» после возврата даёт ту же картину (идемпотентно, без дублей)
  const again = computeIntervalState({ executionStartedAtMs: start, nowMs: start + 25_000, ...interval });
  assert.deepEqual(again, back);
});

test("interval: возврат после 5 минут при 3-минутном блоке — done", () => {
  const start = 1_000_000;
  const state = computeIntervalState({ executionStartedAtMs: start, nowMs: start + 300_000, ...interval });
  assert.equal(state.phase, "done");
  assert.equal(state.remainingTotalSeconds, 0);
});
