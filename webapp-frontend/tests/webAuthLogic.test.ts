import assert from "node:assert/strict";
import { test } from "node:test";

import {
  formatCountdown, nextPollDelayMs, phaseAfterPoll, secondsLeft, spokenCode,
} from "../src/platform/webAuthLogic.ts";

test("nextPollDelayMs: базовый интервал, мягкий рост каждые 20 опросов, потолок 6 с", () => {
  assert.equal(nextPollDelayMs(0, 2), 2000);
  assert.equal(nextPollDelayMs(19, 2), 2000);
  assert.equal(nextPollDelayMs(20, 2), 3000);
  assert.equal(nextPollDelayMs(40, 2), 4000);
  assert.equal(nextPollDelayMs(1000, 2), 6000);
});

test("nextPollDelayMs: при 429 пауза втрое длиннее, потолок 15 с; нулевой интервал не даёт busy-loop", () => {
  assert.equal(nextPollDelayMs(0, 2, true), 6000);
  assert.equal(nextPollDelayMs(1000, 2, true), 15000);
  assert.equal(nextPollDelayMs(0, 0), 1000);
});

test("secondsLeft/formatCountdown: 300 с -> 5:00, 65 с -> 1:05, не уходит в минус", () => {
  assert.equal(secondsLeft(300_000, 0), 300);
  assert.equal(secondsLeft(1_500, 0), 2);
  assert.equal(secondsLeft(0, 10_000), 0);
  assert.equal(formatCountdown(300), "5:00");
  assert.equal(formatCountdown(65), "1:05");
  assert.equal(formatCountdown(0), "0:00");
});

test("spokenCode: цифры через пробел", () => {
  assert.equal(spokenCode("4821"), "4 8 2 1");
});

test("phaseAfterPoll: терминальные статусы переводят экран, pending/too_many — нет", () => {
  assert.deepEqual(phaseAfterPoll("signed_in"), { kind: "signed_in" });
  assert.deepEqual(phaseAfterPoll("denied"), { kind: "denied" });
  assert.deepEqual(phaseAfterPoll("expired"), { kind: "expired" });
  assert.deepEqual(phaseAfterPoll("not_found"), { kind: "expired" });
  assert.equal(phaseAfterPoll("pending"), null);
  assert.equal(phaseAfterPoll("too_many"), null);
});
