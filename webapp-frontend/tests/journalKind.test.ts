import assert from "node:assert/strict";
import { test } from "node:test";

import { JOURNAL_KIND_LABELS, journalKind } from "../src/journalKind.ts";

test("journalKind: тип записи по source/activity_type", () => {
  assert.equal(journalKind({ source: "plan" }), "plan");
  assert.equal(journalKind({ source: "elective" }), "elective");
  assert.equal(journalKind({ source: "freeform" }), "freeform");
  assert.equal(journalKind({ source: "freeform", activity_type: "swimming" }), "logged");
  assert.equal(journalKind({ source: "backdated" }), "backdated");
  // задним числом важнее типа активности
  assert.equal(journalKind({ source: "backdated", activity_type: "swimming" }), "backdated");
  assert.equal(JOURNAL_KIND_LABELS.backdated, "Записана задним числом");
});
