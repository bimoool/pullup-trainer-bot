import assert from "node:assert/strict";
import { test } from "node:test";

import { backButtonAction } from "../src/liveDialog.ts";
import type { LiveSessionCompleteResponse } from "../src/apiV2.ts";
import {
  canStartNextBlock, carriesCompletionOutcome, classifySyncError, finishStatus, isFinishedElsewhere, summaryResult,
  type SyncFailure,
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

// --- Summary движка v2: итог первого завершения, а не ответ «Сохранить» -----------------------------------

const COURSE_PROGRESSION = {
  workout_role: "A", next_workout_role: "B", qualified: true, pending_inputs: [],
  blocks: [{ block_role: "a_volume", decision: "add_mandatory_rep" }],
} as unknown as LiveSessionCompleteResponse["course_progression"];

function response(fields: Partial<LiveSessionCompleteResponse>): LiveSessionCompleteResponse {
  return {
    id: 7, status: "completed", effort: null, comment: null, progression_result: null, progression_skipped_reason: null,
    course_progression: null, ...fields,
  } as LiveSessionCompleteResponse;
}

/** Ответ «Сохранить» (POST …/complete уже завершённой сессии): оценка записана, прогрессия — нет. */
const SAVE = response({ effort: "3", comment: "ок", progression_skipped_reason: "already_completed" });

test("Summary: первое штатное завершение V5.6 — прибавка курса, без ложного «уже была завершена»", () => {
  const first = response({ course_progression: COURSE_PROGRESSION });
  const shown = summaryResult(first, SAVE);
  assert.deepEqual(shown.course_progression, COURSE_PROGRESSION);
  assert.equal(shown.progression_skipped_reason, null);
  assert.equal(shown.effort, "3");  // оценка/заметка — из последнего ответа
  assert.equal(shown.comment, "ок");
});

test("Summary: раннее завершение — «досрочно», не «уже была завершена»", () => {
  const shown = summaryResult(response({ progression_skipped_reason: "abandoned" }), SAVE);
  assert.equal(shown.progression_skipped_reason, "abandoned");
  assert.equal(shown.course_progression, null);
});

test("Summary: тренировка вне курса — без баннера (not_plan_session), не «уже была завершена»", () => {
  assert.equal(summaryResult(response({ progression_skipped_reason: "not_plan_session" }), SAVE).progression_skipped_reason, "not_plan_session");
});

test("Summary: настоящий повтор (экран завершения не видел) — честный ответ сервера", () => {
  assert.deepEqual(summaryResult(null, SAVE), SAVE);
});

test("carriesCompletionOutcome: только ответ, завершивший тренировку (а не ответ событий уже завершённой)", () => {
  assert.equal(carriesCompletionOutcome(response({ course_progression: COURSE_PROGRESSION })), true);
  assert.equal(carriesCompletionOutcome(response({ progression_skipped_reason: "abandoned" })), true);
  assert.equal(carriesCompletionOutcome(response({})), false);
  assert.equal(carriesCompletionOutcome(response({ status: "started" })), false);
});
