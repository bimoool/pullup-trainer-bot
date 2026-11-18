import { expect, test, type Page } from "@playwright/test";

import { buildInitData, launchUrl } from "../../e2e-staging/fixtures/initData";

// Saving consumes the fixture's fresh test day. A retry must not reuse its saved/cooldown state.
test.describe.configure({ retries: 0 });

// Each identity has its own v5_one_rep_max fixture in scripts/e2e_seed_all.sh.
// Signed launch parameters exercise the actual SDK parser; React and API responses stay real.
async function openTest(page: Page, telegramId: number) {
  const signed = buildInitData(telegramId, process.env.BOT_TOKEN!);
  await page.goto(launchUrl(test.info().project.use.baseURL!, signed, "android"));
  await page.getByRole("button", { name: "Планы", exact: true }).click();
  await page.getByRole("button", { name: /^Начать: Подтягивания/ }).first().click();
  await page.getByTestId("one-rm-start").click();
  await expect(page.getByTestId("one-rm-next")).toContainText("Подход 1 из 8");
}

async function reachSingle(page: Page) {
  await page.getByTestId("one-rm-success").click();
  await expect(page.getByTestId("one-rm-next")).toContainText("Подход 2 из 8");
  await page.getByTestId("one-rm-success").click();
  await expect(page.getByTestId("one-rm-next")).toContainText("Подход 3 из 8");
}

async function finishConfirmed(page: Page) {
  await reachSingle(page);
  await page.getByTestId("one-rm-speed").getByRole("button", { name: "Получилось · Медленно" }).click();
  await expect(page.getByTestId("one-rm-next")).toContainText("Подход 4 из 8");
  await page.getByTestId("one-rm-fail").click();
}

test("saved confirmed 1RM text survives readiness reload and ends with the pre-screen", async ({ page }) => {
  await openTest(page, 93520001);
  await finishConfirmed(page);
  // A failed write must not promote a result. The existing retry then records it once.
  await page.route("**/course/one-rep-max", (route) => route.abort(), { times: 1 });
  await page.getByTestId("one-rm-save").click();
  await expect(page.getByTestId("one-rm-error")).toBeVisible();
  await expect(page.getByTestId("one-rm-result")).toHaveCount(0);
  const response = page.waitForResponse((r) => r.url().endsWith("/course/one-rep-max") && r.ok());
  await page.getByTestId("one-rm-save").click();
  expect((await (await response).json()).one_rep_max.e1rm_kg).toBe("15");
  await expect(page.getByTestId("session-pre")).toBeVisible();
  await expect(page.getByTestId("one-rm-result")).toContainText("15");
  await expect(page.getByTestId("one-rm-result")).toHaveCount(1);
  await page.getByTestId("session-pre-back").click();
  await page.getByRole("button", { name: /^Начать: Подтягивания/ }).first().click();
  await expect(page.getByTestId("session-pre")).toBeVisible();
  await expect(page.getByTestId("one-rm-result")).toHaveCount(0);
});

test("stopped test preserves the existing unconfirmed copy and does not unlock weights", async ({ page }) => {
  await openTest(page, 93520002);
  await reachSingle(page);
  await page.getByTestId("one-rm-speed").getByRole("button", { name: "Получилось · Обычно" }).click();
  await expect(page.getByTestId("one-rm-next")).toContainText("Подход 4 из 8");
  const response = page.waitForResponse((r) => r.url().endsWith("/course/one-rep-max") && r.ok());
  await page.getByTestId("one-rm-stop").click();
  const saved = (await (await response).json()).one_rep_max;
  expect(saved).toMatchObject({ outcome: "stopped", confirmed: false, e1rm_kg: null, last_successful_single_kg: "15" });
  await expect(page.getByTestId("one-rm-result")).toHaveText(
    "Тест остановлен вами и сохранён (последний успешный одиночный: +15 кг). Это не подтверждённый 1RM — вес силовых подходов по нему не назначается.",
  );
  await expect(page.getByTestId("course-setup-required")).toBeVisible();
  await expect(page.getByTestId("session-pre")).toHaveCount(0);
});

test("completed test without a single preserves the no-1RM outcome", async ({ page }) => {
  await openTest(page, 93520003);
  await reachSingle(page);
  await page.getByTestId("one-rm-fail").click();
  const response = page.waitForResponse((r) => r.url().endsWith("/course/one-rep-max") && r.ok());
  await page.getByTestId("one-rm-save").click();
  expect((await (await response).json()).one_rep_max).toMatchObject({ outcome: "completed", confirmed: false, e1rm_kg: null });
  await expect(page.getByTestId("one-rm-result")).toHaveText(
    "Тест окончен и сохранён, но успешного одиночного подхода нет — 1RM не назначен.",
  );
  await expect(page.getByTestId("course-setup-required")).toBeVisible();
});

test("readiness error hides the saved result; retry restores it only to the same course", async ({ page }) => {
  await openTest(page, 93520004);
  await finishConfirmed(page);
  await page.route("**/api/v2/dashboard/status", (route) => route.abort(), { times: 1 });
  await page.getByTestId("one-rm-save").click();
  await expect(page.getByText(/Не удалось загрузить:/)).toBeVisible();
  await expect(page.getByTestId("one-rm-result")).toHaveCount(0);
  await page.getByRole("button", { name: "Повторить", exact: true }).click();
  await expect(page.getByTestId("session-pre")).toBeVisible();
  await expect(page.getByTestId("one-rm-result")).toContainText("1RM: +15 кг");
});
