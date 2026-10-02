import assert from "node:assert/strict";
import { test } from "node:test";

import {
  formatPeerCohort, formatPeerMedian, formatPeerNext, formatPeerPercentile, peerBarWidth, PEER_INSUFFICIENT_TEXT,
  PEER_RATE_LIMITED_TEXT, peerView, type PeerInsights,
} from "../src/peerInsightsFormat.ts";

const ok: PeerInsights = {
  status: "ok", min_cohort_size: 20, unit: "повт.", own_value: "12",
  cohort: { level: "gender_age", label: "Мужчины 30–39 лет", size_bucket: "20–49" },
  percentile: 70, median: "10.5", next_target: { percentile: 75, value: "15.25" },
};

test("insufficient text is the exact contract string", () => {
  assert.equal(PEER_INSUFFICIENT_TEXT, "Пока мало данных для сравнения (нужно ≥20 человек)");
});

test("peerView: ok only with a full aggregate set, never synthesizes numbers", () => {
  assert.equal(peerView(ok), "ok");
  assert.equal(peerView({ ...ok, status: "insufficient", cohort: null, percentile: null, median: null }), "insufficient");
  assert.equal(peerView({ ...ok, status: "no_result", cohort: null, percentile: null, median: null }), "no_result");
  assert.equal(peerView({ ...ok, median: null }), "insufficient"); // неполные данные -> честное «мало данных»
  assert.equal(peerView({ ...ok, status: "unknown" }), "insufficient");
});

test("formatters", () => {
  assert.equal(formatPeerCohort(ok.cohort!), "Мужчины 30–39 лет · 20–49 человек");
  assert.equal(formatPeerPercentile(70), "Лучше, чем у ~70% похожих");
  assert.equal(formatPeerPercentile(10), "Лучше, чем у ~10% похожих");
  assert.equal(formatPeerPercentile(0), "Лучше, чем у менее 10% похожих"); // нижняя полоса — честно «менее 10%»
  assert.equal(formatPeerMedian("10.5", "повт."), "Медиана: 10.5 повт.");
  assert.equal(formatPeerMedian("8", ""), "Медиана: 8");
});

test("formatPeerNext: reps round up to a whole rep, other metrics keep decimals", () => {
  assert.equal(formatPeerNext(ok.next_target!, "повт.", true), "Следующий ориентир: 16 повт. — лучше, чем у 75% похожих");
  assert.equal(formatPeerNext({ percentile: 50, value: "42.5" }, "сек", false), "Следующий ориентир: 42.5 сек — лучше, чем у 50% похожих");
  assert.equal(formatPeerNext({ percentile: 90, value: "15" }, "повт.", true), "Следующий ориентир: 15 повт. — лучше, чем у 90% похожих");
});

test("peerBarWidth clamps", () => {
  assert.equal(peerBarWidth(73), 73);
  assert.equal(peerBarWidth(-5), 0);
  assert.equal(peerBarWidth(140), 100);
  assert.equal(peerBarWidth(Number.NaN), 0);
});

test("rate-limited text is friendly Russian copy", () => {
  assert.equal(PEER_RATE_LIMITED_TEXT, "Слишком много запросов сравнения. Попробуйте чуть позже.");
});
