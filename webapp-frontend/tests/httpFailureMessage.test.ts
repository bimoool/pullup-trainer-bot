import assert from "node:assert/strict";
import { test } from "node:test";

import { submitOnboardingQuestionnaire } from "../src/api.ts";
import { CourseApiError, postOneRepMaxNextSet, putCourseInputs } from "../src/apiV2.ts";
import { describeCourseError } from "../src/courseV5.ts";
import { httpFailureMessage } from "../src/sessionErrors.ts";

/**
 * Первый обычный пользователь на staging: при ответе без строкового `detail` (422 Pydantic — массив, 409 только с
 * кодом) экран показывал «PUT /api/v2/program-inclusions/…/course/inputs failed: 422». Теперь — человеческий текст
 * с кодом ответа; status/code ошибки не меняются.
 */
async function withFetch<T>(status: number, body: unknown, run: () => Promise<T>): Promise<T> {
  const realFetch = globalThis.fetch;
  globalThis.fetch = (async () => new Response(JSON.stringify(body), {
    status, headers: { "Content-Type": "application/json" },
  })) as typeof fetch;
  try {
    return await run();
  } finally {
    globalThis.fetch = realFetch;
  }
}

function assertHuman(message: string, status: number) {
  assert.doesNotMatch(message, /\/api\//);
  assert.doesNotMatch(message, /failed/);
  assert.match(message, new RegExp(`Код ${status}\\.$`));
}

test("httpFailureMessage: по-русски, с кодом, без адреса запроса", () => {
  for (const status of [400, 404, 409, 422, 500, 503, 418]) {
    assertHuman(httpFailureMessage(status), status);
  }
  assert.match(httpFailureMessage(422), /не принял введённые данные/);
});

test("PUT …/course/inputs 422 (Pydantic, detail — массив): текст для человека, status сохранён", async () => {
  const detail = [{ type: "decimal_parsing", loc: ["body", "load_step_kg"], msg: "Input should be a valid decimal" }];
  const error = await withFetch(422, { detail }, () => putCourseInputs("init", 7, { load_step_kg: "abc" })).then(
    () => assert.fail("должна быть ошибка"), (e: unknown) => e,
  );
  assert.ok(error instanceof CourseApiError);
  assert.equal(error.status, 422);
  assertHuman(error.message, 422);
  assertHuman(describeCourseError(error, "сохранить"), 422);
});

test("POST …/one-rep-max/next-set 409 course_setup_required: код и missing сохранены, текст не адрес", async () => {
  const error = await withFetch(
    409, { detail: { code: "course_setup_required", missing: ["load_step"] } },
    () => postOneRepMaxNextSet("init", 7, []),
  ).then(() => assert.fail("должна быть ошибка"), (e: unknown) => e as CourseApiError);
  assert.equal(error.code, "course_setup_required");
  assert.deepEqual(error.missing, ["load_step"]);
  assertHuman(error.message, 409);
});

test("POST /api/onboarding/questionnaire 422: анкета показывает текст для человека, не адрес", async () => {
  const error = await withFetch(422, { detail: [{ loc: ["body", "height_cm"], msg: "Input should be greater than 0" }] }, () =>
    submitOnboardingQuestionnaire("init", {
      weight_kg: "80", height_cm: 0, gender: "male", birth_date: "1992-04-15", timezone: "Europe/Moscow",
    })).then(() => assert.fail("должна быть ошибка"), (e: unknown) => e as Error);
  assertHuman(error.message, 422);
});

test("строковый detail сервера по-прежнему показывается как есть", async () => {
  const error = await withFetch(409, { detail: { code: "one_rep_max_too_soon", message: "Тест 1RM — не раньше чем через 48 часов." } },
    () => postOneRepMaxNextSet("init", 7, [])).then(() => assert.fail("должна быть ошибка"), (e: unknown) => e as CourseApiError);
  assert.equal(error.message, "Тест 1RM — не раньше чем через 48 часов.");
  assert.equal(error.code, "one_rep_max_too_soon");
});
