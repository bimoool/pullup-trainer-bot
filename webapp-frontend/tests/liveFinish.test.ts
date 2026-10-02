import assert from "node:assert/strict";
import { test } from "node:test";

import { backButtonAction } from "../src/liveDialog.ts";
import {
  canStartNextBlock, classifySyncError, finishStatus, isFinishedElsewhere, type SyncFailure,
} from "../src/liveFinish.ts";

const httpError = (status: number, message = "boom") => Object.assign(new Error(message), { status });
const transient: SyncFailure = { kind: "transient", message: "Failed to fetch", status: null };
const rejected: SyncFailure = { kind: "rejected", message: "Live session not found", status: 404 };
const auth: SyncFailure = { kind: "auth", message: "expired", status: 401 };

test("classifySyncError: сеть/5xx/408/429 — временные, 4xx — отказ, 401 — initData", () => {
  assert.deepEqual(classifySyncError(new TypeError("Failed to fetch")), { kind: "transient", message: "Failed to fetch", status: null });
  assert.equal(classifySyncError(httpError(500)).kind, "transient");
  assert.equal(classifySyncError(httpError(503)).kind, "transient");
  assert.equal(classifySyncError(httpError(408)).kind, "transient");
  assert.equal(classifySyncError(httpError(429)).kind, "transient");
  assert.deepEqual(classifySyncError(httpError(404, "Live session not found")), rejected);
  assert.equal(classifySyncError(httpError(422)).kind, "rejected");
  assert.equal(classifySyncError(httpError(409)).kind, "rejected");
  assert.equal(classifySyncError(httpError(401)).kind, "auth");
  assert.equal(classifySyncError("plain string").message, "plain string");
  assert.equal(classifySyncError(null).status, null);
});

test("finishStatus: без завершения в очереди — none", () => {
  for (const online of [true, false]) {
    for (const syncing of [true, false]) {
      assert.equal(finishStatus({ finishing: false, online, syncing, failure: rejected }), "none");
    }
  }
});

test("finishStatus: офлайн — ждём сеть, независимо от прошлой ошибки и флаша", () => {
  assert.equal(finishStatus({ finishing: true, online: false, syncing: false, failure: null }), "offline");
  assert.equal(finishStatus({ finishing: true, online: false, syncing: true, failure: transient }), "offline");
  assert.equal(finishStatus({ finishing: true, online: false, syncing: false, failure: rejected }), "offline");
});

test("finishStatus: онлайн и флаш в полёте — sending", () => {
  assert.equal(finishStatus({ finishing: true, online: true, syncing: true, failure: null }), "sending");
  assert.equal(finishStatus({ finishing: true, online: true, syncing: true, failure: rejected }), "sending");
});

test("finishStatus: онлайн без флаша — всегда есть повтор (нет тупика), отказ сервера — rejected", () => {
  // Переоткрыли онлайн: ошибки ещё не было, флаш не идёт — повтор всё равно доступен (#287 HIGH 1).
  assert.equal(finishStatus({ finishing: true, online: true, syncing: false, failure: null }), "retry");
  assert.equal(finishStatus({ finishing: true, online: true, syncing: false, failure: transient }), "retry");
  assert.equal(finishStatus({ finishing: true, online: true, syncing: false, failure: rejected }), "rejected");
  assert.equal(finishStatus({ finishing: true, online: true, syncing: false, failure: auth }), "rejected");
});

test("isFinishedElsewhere: только 404 и сессия больше не активна на сервере", () => {
  assert.equal(isFinishedElsewhere(rejected, null, 7), true);
  assert.equal(isFinishedElsewhere(rejected, 8, 7), true);
  assert.equal(isFinishedElsewhere(rejected, 7, 7), false, "сессия ещё идёт — настоящий отказ");
  assert.equal(isFinishedElsewhere({ ...rejected, status: 422 }, null, 7), false);
  assert.equal(isFinishedElsewhere(transient, null, 7), false);
});

test("canStartNextBlock: «Начать» блока недоступно, пока завершение в очереди (#287 HIGH 2)", () => {
  assert.equal(canStartNextBlock({ completeRequested: null }), true);
  assert.equal(canStartNextBlock({ completeRequested: { abandoned: false } }), false);
  assert.equal(canStartNextBlock(null), false);
});

test("backButtonAction: завершение в очереди — Back уводит с экрана, если есть куда", () => {
  assert.equal(backButtonAction({ reviewOpen: false, finishing: true, canLeave: true }), "leave");
  assert.equal(backButtonAction({ reviewOpen: false, finishing: true, canLeave: false }), "ignore");
  assert.equal(backButtonAction({ reviewOpen: true, finishing: true, canLeave: true }), "close-review");
  assert.equal(backButtonAction({ reviewOpen: false, finishing: false, canLeave: true }), "confirm-finish");
});
