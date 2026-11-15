import { expect, test, type Page } from "@playwright/test";

import { buildInitData, getTestBotToken } from "../fixtures/initData";
import { openAppAs } from "../fixtures/setup";

// Dedicated synthetic identity, seeded by e2e_seed_all.sh; no shared mutable Builder fixture.
const USER = 920_005;
test.describe.configure({ mode: "serial" });

async function openItemEditor(page: Page, suffix: string) {
  const headers = { "X-Telegram-Init-Data": buildInitData({ id: USER, firstName: "E2E" }, getTestBotToken()) };
  const exercises = await page.request.get("/api/v2/exercises", { headers });
  expect(exercises.ok()).toBe(true);
  const exercise = (await exercises.json()).exercises[0];
  const title = `Отдых ${suffix} ${Date.now()}`;
  const created = await page.request.post("/api/v2/workouts", { headers, data: { title } });
  expect(created.ok()).toBe(true);
  const workout = await created.json();
  const added = await page.request.post(`/api/v2/workouts/${workout.id}/items`, {
    headers, data: { exercise_id: exercise.id, protocol: {
      type: "reps_sets", prescription: { source: "static", sets: 3, reps: 8 }, rest_seconds: 60,
    } },
  });
  expect(added.ok()).toBe(true);
  const item = await added.json();
  await openAppAs(page, USER, { allowedApiStatuses: [503] });
  await page.getByTestId("my-workout-card").filter({ hasText: title }).click();
  await page.getByRole("button", { name: "Изменить", exact: true }).click();
  await page.getByTestId("workout-item").getByRole("button", { name: /^Изменить:/ }).click();
  return { headers, title, workout, item, url: `/api/v2/workouts/${workout.id}/items/${item.id}` };
}

test("invalid rest stays visible and blocks saving instead of silently saving the old rest", async ({ page }) => {
  await openItemEditor(page, "валидация");
  const rest = page.getByRole("textbox", { name: "Отдых между подходами", exact: true });
  for (const value of ["", "00:99"]) {
    await rest.fill(value);
    await expect(page.getByRole("button", { name: "Сохранить", exact: true })).toBeDisabled();
    await expect(rest).toHaveAttribute("aria-invalid", "true");
    await expect(page.getByRole("alert").filter({ hasText: /Отдых/ }).first()).toBeVisible();
    await rest.blur();
    await expect(rest).toHaveValue(value);
  }
  await rest.fill("01:30");
  await expect(page.getByRole("button", { name: "Сохранить", exact: true })).toBeEnabled();
});

test("rest and reps PATCH persist after reload and the next default-v2 start uses the saved rest", async ({ page }) => {
  const { headers, title, workout, url } = await openItemEditor(page, "сохранение");
  await page.getByRole("textbox", { name: "Отдых между подходами", exact: true }).fill("01:30");
  await page.getByRole("textbox", { name: "Повторения в подходе", exact: true }).fill("12");
  const patched = page.waitForResponse((r) => r.url().endsWith(url) && r.request().method() === "PATCH");
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  const response = await patched;
  expect(response.status()).toBe(200);
  expect(response.request().postDataJSON().protocol.rest_seconds).toBe(90);
  expect((await response.json()).protocol.prescription.reps).toBe(12);
  await expect(page.getByTestId("workout-item")).toContainText("1:30");
  await page.reload();
  await page.getByTestId("my-workout-card").filter({ hasText: title }).click();
  await page.getByRole("button", { name: "Изменить", exact: true }).click();
  await page.getByTestId("workout-item").getByRole("button", { name: /^Изменить:/ }).click();
  await expect(page.getByRole("textbox", { name: "Отдых между подходами", exact: true })).toHaveValue("01:30");
  await expect(page.getByRole("textbox", { name: "Повторения в подходе", exact: true })).toHaveValue("12");
  await page.getByRole("button", { name: "Отмена", exact: true }).click();
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  await expect(page.getByTestId("workout-detail")).toBeVisible();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  const started = page.waitForResponse((r) => r.url().endsWith("/api/v2/sessions/live") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  const live = await started;
  expect(live.status()).toBe(200);
  expect(live.request().postDataJSON().engine_version).toBe(2);
  await expect(page.getByTestId("engine-phase")).toHaveText("Приготовься");
  await page.getByTestId("engine-skip").click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл");
  await page.getByLabel("Результат подхода").fill("12");
  await page.getByTestId("engine-submit").click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых");
  await expect(page.getByTestId("engine-timer")).toHaveText(/^1:(29|30)$/);
  // Finish this synthetic session so the next scenario starts without an active session.
  await page.getByTestId("engine-finish").click();
  await page.getByTestId("engine-finish-confirm").click();
  await expect(page.getByTestId("workout-detail").or(page.getByText("Тренировка завершена"))).toBeVisible();
  const persisted = await page.request.get(`/api/v2/workouts/${workout.id}`, { headers });
  expect((await persisted.json()).items[0].protocol.rest_seconds).toBe(90);
});

test("failed PATCH is visible, preserves the draft, and a pending retry cannot write twice", async ({ page }) => {
  const { url } = await openItemEditor(page, "повтор");
  const rest = page.getByRole("textbox", { name: "Отдых между подходами", exact: true });
  await rest.fill("01:30");
  await page.getByRole("textbox", { name: "Повторения в подходе", exact: true }).fill("12");
  let requests = 0;
  let releaseRetry: () => void = () => {};
  const retryGate = new Promise<void>((resolve) => { releaseRetry = resolve; });
  await page.route(`**${url}`, async (route) => {
    if (route.request().method() !== "PATCH") return route.continue();
    requests += 1;
    if (requests === 1) return route.fulfill({ status: 503, json: { detail: "Временная ошибка" } });
    await retryGate;
    await route.continue();
  });
  const save = page.getByRole("button", { name: "Сохранить", exact: true });
  await save.click();
  await expect(page.getByRole("alert").filter({ hasText: /Не удалось сохранить/ })).toBeVisible();
  await expect(rest).toHaveValue("01:30");
  await expect(page.getByRole("textbox", { name: "Повторения в подходе", exact: true })).toHaveValue("12");
  await save.click();
  await expect(save).toBeDisabled();
  await expect.poll(() => requests).toBe(2);
  await save.dispatchEvent("click");
  expect(requests).toBe(2);
  releaseRetry();
  await expect(page.getByTestId("workout-item")).toContainText("1:30");
  await expect(page.getByTestId("workout-item")).toContainText("3 × 12");
  expect(requests).toBe(2);
});
