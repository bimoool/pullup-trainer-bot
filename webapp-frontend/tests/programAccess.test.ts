import assert from "node:assert/strict";
import { test } from "node:test";

import { courseRequiresPremium } from "../src/programAccess.ts";

const plan = {
  program_inclusions: [
    { id: 1, is_active: true, access_level: "free" as const },
    { id: 2, is_active: true, access_level: "premium" as const },
    { id: 3, is_active: true },
  ],
  plan_items: [
    { id: 10, program_inclusion_id: 1 },
    { id: 20, program_inclusion_id: 2 },
    { id: 30, program_inclusion_id: 3 },
    { id: 40, program_inclusion_id: null },
  ],
};

test("free program rows do not need Premium (Подтягивания free forever)", () => {
  assert.equal(courseRequiresPremium(plan, [10]), false);
  assert.equal(courseRequiresPremium(plan, [10, 40]), false);
});

test("premium program rows, or a missing access_level, need Premium", () => {
  assert.equal(courseRequiresPremium(plan, [20]), true);
  assert.equal(courseRequiresPremium(plan, [30]), true);
  assert.equal(courseRequiresPremium(plan, [10, 20]), true);
});

test("without explicit rows the active inclusions decide; nothing resolvable stays conservative", () => {
  assert.equal(
    courseRequiresPremium({ program_inclusions: [{ id: 1, is_active: true, access_level: "free" }], plan_items: [] }, undefined),
    false,
  );
  assert.equal(courseRequiresPremium(plan, undefined), true);
  assert.equal(courseRequiresPremium(null, [10]), true);
  assert.equal(courseRequiresPremium(plan, [40]), true);
});
