import { expect, test, type Page } from "@playwright/test";

import { buildInitData, getTestBotToken } from "../fixtures/initData";
import { openAppAs } from "../fixtures/setup";
import { pressTelegramBackButton } from "../fixtures/telegramMock";

// Independent read-only fixtures, including CI retry identities. The active course has
// no history, so readiness does not depend on a last-session date or week boundary.
// scripts/e2e_seed_all.sh: plan_week_start_session / home_workouts.
const COURSE_USER = 939_981;
const EMPTY_USER = 939_971;
const PLAN = "/api/v2/plan";
const PROGRAMS = "/api/v2/programs";

async function membership(page: Page, telegramId: number) {
  const response = await page.request.get(PLAN, {
    headers: { "X-Telegram-Init-Data": buildInitData({ id: telegramId, firstName: "E2E" }, getTestBotToken()) },
  });
  expect(response.ok()).toBe(true);
  const { plan } = await response.json();
  return plan.program_inclusions;
}

function trackWrites(page: Page) {
  const writes: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/") && request.method() !== "GET") {
      writes.push(`${request.method()} ${new URL(request.url()).pathname}`);
    }
  });
  return writes;
}

function expectOnlyFaults(errors: { apiFailures: string[]; consoleErrors: string[] }, page: Page, path: string, count: number, status = 500) {
  expect(errors.apiFailures).toEqual(Array(count).fill(`${status} ${new URL(path, page.url()).href}`));
  expect(errors.consoleErrors).toEqual(Array(count).fill(
    expect.stringMatching(new RegExp(`^Failed to load resource: the server responded with a status of ${status} \\(`)),
  ));
}

test("plan failure preserves catalog/detail, blocks unknown membership actions, and retries without duplicates", async ({ page }, testInfo) => {
  const uid = COURSE_USER + testInfo.retry;
  const before = await membership(page, uid);
  expect(before.filter((inclusion: { is_active: boolean }) => inclusion.is_active)).toHaveLength(1);
  const writes = trackWrites(page);
  let failPlan = true;
  await page.route(`**${PLAN}`, (route) => failPlan
    ? route.fulfill({ status: 500, json: { detail: "Synthetic plan unavailable" } })
    : route.continue());
  const programsResponse = page.waitForResponse((response) => new URL(response.url()).pathname === PROGRAMS);
  const errors = await openAppAs(page, uid, { backButton: true });
  expect((await programsResponse).status()).toBe(200);

  const course = page.locator(".program-card-button").filter({ hasText: "Подтягивания" }).first();
  await expect(course).toBeVisible();
  await expect(page.getByTestId("home-plan-unavailable")).toContainText("Не удалось загрузить план");
  await expect(page.getByTestId("home-training-start")).toHaveCount(0);
  await expect(page.getByTestId("home-training-wait")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Баннер: план дня пуст" })).toHaveCount(0);
  await expect(course).not.toContainText("В плане");
  await course.click();
  await expect(page.getByTestId("program-detail-title")).toHaveText("Подтягивания");
  await expect(page.getByTestId("program-schedule")).toBeVisible();
  await expect(page.getByTestId("program-plan-unavailable")).toContainText("Не удалось загрузить план");
  await expect(page.getByRole("button", { name: "План недоступен", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Добавить в план", exact: true })).toHaveCount(0);

  failPlan = false;
  await page.getByRole("button", { name: "Повторить загрузку плана" }).click();
  await expect(page.getByRole("button", { name: "В плане", exact: true })).toBeDisabled();
  await expect(page.getByTestId("program-plan-unavailable")).toHaveCount(0);
  await pressTelegramBackButton(page);
  await expect(course).toContainText("В плане");
  await expect(page.getByTestId("home-training-start")).toBeVisible();
  await expect(page.getByTestId("home-plan-unavailable")).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("home-training-start")).toBeVisible();
  expect(await membership(page, uid)).toEqual(before);
  expect(writes).toEqual([]);
  expectOnlyFaults(errors, page, PLAN, 1);
});

test("catalog and detail stay available while plan membership is still loading", async ({ page }, testInfo) => {
  let releasePlan!: () => void;
  const heldPlan = new Promise<void>((resolve) => { releasePlan = resolve; });
  await page.route(`**${PLAN}`, async (route) => {
    await heldPlan;
    await route.continue();
  });
  const { apiFailures, consoleErrors } = await openAppAs(page, COURSE_USER + testInfo.retry, { backButton: true });
  try {
    await page.locator(".program-card-button").filter({ hasText: "Подтягивания" }).first().click();
    await expect(page.getByTestId("program-detail-title")).toHaveText("Подтягивания");
    await expect(page.getByRole("button", { name: "Загружаю план…", exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Добавить в план", exact: true })).toHaveCount(0);
    releasePlan();
    await expect(page.getByRole("button", { name: "В плане", exact: true })).toBeDisabled();
    expect(apiFailures).toEqual([]);
    expect(consoleErrors).toEqual([]);
  } finally {
    releasePlan();
  }
});

test("catalog fetch failure with a known empty plan gives Home a direct create fallback", async ({ page }, testInfo) => {
  await page.route(`**${PROGRAMS}`, (route) => route.fulfill({ status: 500, json: { detail: "Synthetic catalog unavailable" } }));
  const planResponse = page.waitForResponse((response) => new URL(response.url()).pathname === PLAN);
  const errors = await openAppAs(page, EMPTY_USER + testInfo.retry);
  expect((await planResponse).status()).toBe(200);
  await expect(page.getByText("Не удалось загрузить каталог:", { exact: false })).toBeVisible();
  const fallback = page.getByRole("button", { name: "Баннер: план дня пуст" });
  await expect(fallback).toContainText("Соберите свою тренировку");
  await fallback.click();
  await expect(page.getByPlaceholder("Например, 3 минуты подтягиваний")).toBeVisible();
  expectOnlyFaults(errors, page, PROGRAMS, 1);
});

test("catalog fetch failure gives empty Plans an explicit working create CTA", async ({ page }, testInfo) => {
  await page.route(`**${PROGRAMS}`, (route) => route.fulfill({ status: 500, json: { detail: "Synthetic catalog unavailable" } }));
  const errors = await openAppAs(page, EMPTY_USER + testInfo.retry);
  await expect(page.getByText("Не удалось загрузить каталог:", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Планы", exact: true }).click();
  await expect(page.getByTestId("plans-now-empty")).toContainText("Не удалось загрузить каталог курсов");
  await expect(page.getByTestId("plans-now-open-home")).toHaveCount(0);
  await page.getByTestId("plans-now-create-workout").click();
  await expect(page.getByPlaceholder("Например, 3 минуты подтягиваний")).toBeVisible();
  expectOnlyFaults(errors, page, PROGRAMS, 2);
});

test("recovered empty plan restores Add to plan only after membership is known", async ({ page }, testInfo) => {
  const writes = trackWrites(page);
  await page.route(`**${PLAN}`, (route) => route.fulfill({ status: 500, json: { detail: "Synthetic plan unavailable" } }));
  const errors = await openAppAs(page, EMPTY_USER + testInfo.retry, { backButton: true });
  await expect(page.getByTestId("home-plan-unavailable")).toBeVisible();
  await expect(page.getByRole("button", { name: "Баннер: план дня пуст" })).toHaveCount(0);
  await page.locator(".program-card-button").filter({ hasText: "Подтягивания" }).first().click();
  await expect(page.getByRole("button", { name: "План недоступен", exact: true })).toBeDisabled();
  await page.unroute(`**${PLAN}`);
  await page.getByRole("button", { name: "Повторить загрузку плана" }).click();
  await expect(page.getByRole("button", { name: "Добавить в план", exact: true })).toBeEnabled();
  await pressTelegramBackButton(page);
  await expect(page.getByRole("button", { name: "Баннер: план дня пуст" })).toContainText("Выберите курс в каталоге выше");
  expect(writes).toEqual([]);
  expectOnlyFaults(errors, page, PLAN, 1);
});

test("late failed plan response after leaving Home cannot overwrite recovered Home state", async ({ page }, testInfo) => {
  let releasePlan!: () => void;
  const heldPlan = new Promise<void>((resolve) => { releasePlan = resolve; });
  let first = true;
  await page.route(`**${PLAN}`, async (route) => {
    if (first) {
      first = false;
      await heldPlan;
      await route.fulfill({ status: 500, json: { detail: "Synthetic stale plan failure" } });
    } else {
      await route.continue();
    }
  });
  const errors = await openAppAs(page, COURSE_USER + testInfo.retry);
  try {
    await expect(page.locator(".program-card-button").first()).toBeVisible();
    await page.getByRole("button", { name: "Профиль", exact: true }).click();
    await expect(page.getByTestId("home-header")).toHaveCount(0);
    await page.getByRole("button", { name: "Главная", exact: true }).click();
    await expect(page.getByTestId("home-training-start")).toBeVisible();
    const late = page.waitForResponse((response) => new URL(response.url()).pathname === PLAN && response.status() === 500);
    releasePlan();
    await (await late).finished();
    await expect(page.getByTestId("home-training-start")).toBeVisible();
    await expect(page.getByTestId("home-plan-unavailable")).toHaveCount(0);
    expectOnlyFaults(errors, page, PLAN, 1);
  } finally {
    releasePlan();
  }
});

test("plan 401 preserves the expired-session explanation and blocks membership actions", async ({ page }, testInfo) => {
  await page.route(`**${PLAN}`, (route) => route.fulfill({ status: 401, json: { detail: "Invalid Telegram initData" } }));
  const errors = await openAppAs(page, COURSE_USER + testInfo.retry);
  await expect(page.getByTestId("home-plan-unavailable")).toContainText("Сессия Telegram устарела");
  await expect(page.getByTestId("home-training-start")).toHaveCount(0);
  await page.locator(".program-card-button").filter({ hasText: "Подтягивания" }).first().click();
  await expect(page.getByTestId("program-plan-unavailable")).toContainText("открой его заново из бота");
  await expect(page.getByRole("button", { name: "План недоступен", exact: true })).toBeDisabled();
  await expect(page.getByText("Invalid Telegram initData")).toHaveCount(0);
  expectOnlyFaults(errors, page, PLAN, 1, 401);
});
