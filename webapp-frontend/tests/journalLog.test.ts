import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildActivityPayload, buildBackdatedPayload, dateError, durationError, formatDurationHm, localToday,
  metricForProtocol, parseDurationHm, performedAtFor, setCountForProtocol,
} from "../src/journalLog.ts";

test("parseDurationHm / formatDurationHm", () => {
  assert.equal(parseDurationHm("1:30"), 5400);
  assert.equal(parseDurationHm("0:01"), 60);
  assert.equal(parseDurationHm("12:00"), 43200);
  assert.equal(parseDurationHm("1:5"), null);
  assert.equal(parseDurationHm("90"), null);
  assert.equal(parseDurationHm("1:60"), null);
  assert.equal(formatDurationHm(5400), "1:30");
  assert.equal(formatDurationHm(45 * 60), "0:45");
});

test("durationError: границы 1 мин – 12 ч", () => {
  assert.equal(durationError("0:00") !== null, true);
  assert.equal(durationError("0:01"), null);
  assert.equal(durationError("12:00"), null);
  assert.equal(durationError("12:01") !== null, true);
  assert.equal(durationError("abc") !== null, true);
});

test("dateError: будущее запрещено, сегодня и прошлое можно", () => {
  assert.equal(dateError("2026-10-02", "2026-10-02"), null);
  assert.equal(dateError("2026-09-30", "2026-10-02"), null);
  assert.equal(dateError("2026-10-03", "2026-10-02") !== null, true);
  assert.equal(dateError("", "2026-10-02") !== null, true);
});

test("performedAtFor: сегодня — сейчас, прошлое — полдень этого дня", () => {
  const now = new Date(2026, 9, 2, 8, 15, 0);
  assert.equal(performedAtFor(localToday(now), now), now.toISOString());
  const past = new Date(performedAtFor("2026-09-20", now));
  assert.equal(past.getFullYear(), 2026);
  assert.equal(past.getMonth(), 8);
  assert.equal(past.getDate(), 20);
  assert.equal(past.getHours(), 12);
});

test("setCountForProtocol / metricForProtocol", () => {
  assert.equal(setCountForProtocol({ type: "reps_sets", prescription: { sets: 3, reps: 10 } }), 3);
  assert.equal(setCountForProtocol({ type: "max_effort", prescription: { attempts: 2 } }), 2);
  assert.equal(setCountForProtocol({ type: "interval" }), 1);
  assert.deepEqual(metricForProtocol({ type: "time_sets" }), { metric_type: "time", unit: "s" });
  assert.deepEqual(metricForProtocol({ type: "reps_sets" }), { metric_type: "reps", unit: "reps" });
});

test("buildBackdatedPayload: пропускает пустые подходы, null без данных", () => {
  const now = new Date(2026, 9, 2, 8, 15, 0);
  const payload = buildBackdatedPayload(
    "2026-10-02",
    [
      { exerciseId: 5, protocol: { type: "reps_sets", prescription: { sets: 3 } }, values: ["8", "", "7,5"] },
      { exerciseId: 6, protocol: { type: "time_sets" }, values: ["", ""] },
    ],
    "4", "  заметка ", now,
  );
  assert.ok(payload !== null);
  assert.equal(payload.source, "backdated");
  assert.equal(payload.effort, "4");
  assert.equal(payload.comment, "заметка");
  assert.deepEqual(payload.blocks, [{
    exercise_id: 5,
    sets: [
      { set_number: 1, metric_type: "reps", unit: "reps", value: "8" },
      { set_number: 2, metric_type: "reps", unit: "reps", value: "7.5" },
    ],
  }]);
  assert.equal(buildBackdatedPayload("2026-10-02", [], null, "", now), null);
});

test("buildBackdatedPayload: известная тренировка — все упражнения по порядку + идентичность (#307, D9)", () => {
  const now = new Date(2026, 9, 2, 8, 15, 0);
  const payload = buildBackdatedPayload(
    "2026-10-02",
    [
      { exerciseId: 5, protocol: { type: "reps_sets" }, values: ["6", "6", "5", "4"] },
      { exerciseId: 6, protocol: { type: "time_sets" }, values: ["", ""] },
    ],
    null, "", now, undefined, { workoutDefinitionId: 42, clientSessionId: "c0ffee00-0000-4000-8000-000000000001" },
  );
  assert.ok(payload !== null);
  assert.equal(payload.workout_definition_id, 42);
  assert.equal(payload.client_session_id, "c0ffee00-0000-4000-8000-000000000001");
  assert.deepEqual(payload.blocks.map((block) => block.exercise_id), [5, 6]);
  assert.deepEqual(payload.blocks[0].sets.map((set) => set.value), ["6", "6", "5", "4"]);
  assert.deepEqual(payload.blocks[1].sets, []);
  assert.equal(
    buildBackdatedPayload("2026-10-02", [{ exerciseId: 5, protocol: {}, values: [""] }], null, "", now, undefined, {
      workoutDefinitionId: 42, clientSessionId: "x",
    }),
    null,
  );
});

test("buildActivityPayload", () => {
  const now = new Date(2026, 9, 2, 8, 15, 0);
  const payload = buildActivityPayload("2026-09-30", "running", "1:15", "3", "", now);
  assert.ok(payload !== null);
  assert.equal(payload.source, "freeform");
  assert.equal(payload.activity_type, "running");
  assert.equal(payload.duration_seconds, 4500);
  assert.deepEqual(payload.blocks, []);
  assert.equal(payload.comment, null);
  assert.equal(buildActivityPayload("2026-09-30", "running", "bad", null, "", now), null);
});

test("performedAtFor: сегодня определяется в поясе профиля, а не устройства (#294)", () => {
  const now = new Date("2026-10-04T19:30:00Z"); // 22:30 Москва 04.10; в UTC+5 уже 05.10
  assert.equal(performedAtFor("2026-10-04", now, "Europe/Moscow"), now.toISOString());
  assert.equal(performedAtFor("2026-10-03", now, "Europe/Moscow"), "2026-10-03T09:00:00.000Z");
});
