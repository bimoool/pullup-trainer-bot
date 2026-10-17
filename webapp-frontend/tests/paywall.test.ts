import assert from "node:assert/strict";
import { test } from "node:test";

// paywall.ts шлёт событие через window — в node подставляем EventTarget.
(globalThis as { window?: EventTarget }).window = new EventTarget();

const { reportIfSubscriptionRequired, subscribeSubscriptionRequired, openSubscriptionScreen } = await import(
  "../src/paywall.ts"
);

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

test("402 subscription_required raises one event with the server message; body stays readable", async () => {
  const seen: { message: string | null; openScreen?: boolean }[] = [];
  const unsubscribe = subscribeSubscriptionRequired((detail) => seen.push(detail));
  const response = jsonResponse(402, { detail: { code: "subscription_required", message: "Эта функция доступна с подпиской." } });
  await reportIfSubscriptionRequired(response);
  unsubscribe();
  assert.deepEqual(seen, [{ message: "Эта функция доступна с подпиской." }]);
  assert.equal((await response.json()).detail.code, "subscription_required");
});

test("other errors do not open the paywall", async () => {
  const seen: unknown[] = [];
  const unsubscribe = subscribeSubscriptionRequired((detail) => seen.push(detail));
  await reportIfSubscriptionRequired(jsonResponse(402, { detail: { code: "something_else" } }));
  await reportIfSubscriptionRequired(jsonResponse(409, { detail: { code: "subscription_required" } }));
  await reportIfSubscriptionRequired(new Response("not json", { status: 402 }));
  unsubscribe();
  assert.deepEqual(seen, []);
});

test("openSubscriptionScreen asks App for the subscription screen directly", () => {
  const seen: { openScreen?: boolean }[] = [];
  const unsubscribe = subscribeSubscriptionRequired((detail) => seen.push(detail));
  openSubscriptionScreen();
  unsubscribe();
  assert.equal(seen.length, 1);
  assert.equal(seen[0].openScreen, true);
});
