import assert from "node:assert/strict";
import { test } from "node:test";

import { sanitizeDecimalInput } from "../src/decimalInput.ts";

test("запятая → точка: «12,5» принимается как 12.5", () => {
  assert.equal(sanitizeDecimalInput("12,5"), "12.5");
  assert.equal(sanitizeDecimalInput("0,25"), "0.25");
});

test("лишние разделители и символы отбрасываются", () => {
  assert.equal(sanitizeDecimalInput("1.2.3"), "1.23");
  assert.equal(sanitizeDecimalInput("1,2,3"), "1.23");
  assert.equal(sanitizeDecimalInput("абв12 кг"), "12");
  assert.equal(sanitizeDecimalInput("-5"), "5");
  assert.equal(sanitizeDecimalInput(""), "");
});

test("промежуточный ввод сохраняется: «12,» → «12.»", () => {
  assert.equal(sanitizeDecimalInput("12,"), "12.");
  assert.equal(sanitizeDecimalInput(","), ".");
});
