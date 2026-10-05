import assert from "node:assert/strict";
import { test } from "node:test";

import {
  buildProtocol, draftFromProtocol, intervalRounds, PROTOCOL_KINDS, plural, previewLines, summarizeProtocol,
} from "../src/protocolConfig.ts";

const TECHNICAL = /reps_sets|time_sets|max_effort|interval\b|prescription|static|undefined|NaN|null|\.\d\d\b/;

test("protocol picker uses human titles and explanations, never enum names", () => {
  assert.deepEqual(PROTOCOL_KINDS.map((k) => k.title), ["Повторения", "Время", "Максимум", "Интервалы"]);
  for (const k of PROTOCOL_KINDS) {
    assert.doesNotMatch(`${k.title} ${k.description}`, TECHNICAL);
    assert.ok(k.description.length > 15);
  }
});

test("reps: build → preview → summary agree (one source of truth)", () => {
  const draft = { ...draftFromProtocol(null), kind: "reps_sets" as const, sets: 3, reps: 8, restSeconds: 120 };
  const built = buildProtocol(draft);
  assert.ok(built.ok);
  assert.deepEqual(built.protocol, {
    type: "reps_sets", prescription: { source: "static", sets: 3, reps: 8 }, rest_seconds: 120,
  });
  assert.deepEqual(previewLines(draft), ["3 × 8 повторений", "Отдых между подходами 2:00"]);
  assert.deepEqual(summarizeProtocol(built.protocol).lines, previewLines(draft));
});

test("time: 3 × 30 сек, rest 60", () => {
  const d = { ...draftFromProtocol(null), kind: "time_sets" as const, sets: 3, durationSeconds: 30, restSeconds: 60 };
  assert.deepEqual(previewLines(d), ["3 × 30 сек", "Отдых между подходами 1:00"]);
});

test("max: attempts and rest, no fabricated target", () => {
  const d = { ...draftFromProtocol(null), kind: "max_effort" as const, attempts: 2, maxRestSeconds: 180 };
  assert.deepEqual(previewLines(d), ["2 попытки на максимум", "Отдых между попытками 3:00"]);
  const built = buildProtocol(d);
  assert.ok(built.ok);
  assert.deepEqual(Object.keys(built.protocol.prescription as object).sort(), ["attempts", "source"]);
});

test("interval: rounds derived from total time with the backend formula", () => {
  assert.equal(intervalRounds(180, 30, 30), 3);
  assert.equal(intervalRounds(15, 5, 5), 2);
  assert.equal(intervalRounds(20, 30, 0), 0);
  const d = { ...draftFromProtocol(null), kind: "interval" as const, totalSeconds: 360, workSeconds: 30, intervalRestSeconds: 30 };
  assert.deepEqual(previewLines(d), ["6 раундов", "30 сек работа / 30 сек отдых · всего 6:00"]);
});

test("validation blocks nonsense and never yields NaN", () => {
  const base = draftFromProtocol(null);
  assert.equal(buildProtocol({ ...base, kind: "reps_sets", sets: 0 }).ok, false);
  assert.equal(buildProtocol({ ...base, kind: "reps_sets", reps: 2.5 }).ok, false);
  assert.equal(buildProtocol({ ...base, kind: "reps_sets", sets: NaN }).ok, false);
  assert.equal(buildProtocol({ ...base, kind: "interval", totalSeconds: 10, workSeconds: 30 }).ok, false);
  assert.equal(buildProtocol({ ...base, kind: "max_effort", attempts: 0 }).ok, false);
});

test("existing protocol round-trips through draft without loss", () => {
  const p = { type: "interval", total_duration_seconds: 240, work_seconds: 20, rest_seconds: 10, starts_with: "rest" };
  const built = buildProtocol(draftFromProtocol(p));
  assert.ok(built.ok);
  assert.deepEqual(built.protocol, p);
});

test("summaries never leak technical text", () => {
  for (const p of [
    { type: "reps_sets", prescription: { source: "static", sets: 3, reps: 8 }, rest_seconds: 0 },
    { type: "time_sets", prescription: { source: "static", sets: 2, duration_seconds: 45 }, rest_seconds: 90 },
    { type: "max_effort", prescription: { source: "static", attempts: 1 }, rest_seconds: 0 },
  ]) {
    const s = summarizeProtocol(p);
    assert.doesNotMatch(`${s.kindTitle} ${s.lines.join(" ")}`, TECHNICAL);
  }
});

test("russian plurals", () => {
  assert.equal(plural(1, "раунд", "раунда", "раундов"), "раунд");
  assert.equal(plural(3, "раунд", "раунда", "раундов"), "раунда");
  assert.equal(plural(11, "раунд", "раунда", "раундов"), "раундов");
  assert.equal(plural(21, "раунд", "раунда", "раундов"), "раунд");
});
