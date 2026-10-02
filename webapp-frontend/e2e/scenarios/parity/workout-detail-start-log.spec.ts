import { expect, test } from "@playwright/test";

import { noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";

// Crimpd parity — Workout Detail «Начать» / «Записать» (#273).
// Seed: scripts/e2e_seed.py golden_journey — своя Workout «Золотая тренировка» (reps 2 x 8), пустой
// Журнал. Оба теста пишут сессии: по пользователю на ширину/тему и на retry (id + retry);
// второй тест («Записать») берёт id + 5 + retry.
const USERS = { 320: { id: 998_001, theme: "light" }, 390: { id: 998_011, theme: "dark" } } as const;

for (const width of WIDTHS) {
  const { id, theme } = USERS[width as 320 | 390];
  test.describe(`Workout Detail start/log @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 800 } });
    test.setTimeout(90_000);

    test("«Начать» запускает свободную сессию тренировки (pre → live) без PlanItem", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, id + testInfo.retry, { theme });
      await page.getByTestId("my-workout-card").filter({ hasText: "Золотая тренировка" }).click();
      await expect(page.getByTestId("workout-detail")).toBeVisible();
      await expect(page.getByTestId("workout-detail-start")).toContainText("Начать");
      await expect(page.getByTestId("workout-detail-log")).toContainText("Записать");
      await expectNoHorizontalOverflow(page, "Workout Detail: Начать/Записать");

      await page.getByTestId("workout-detail-start").click();
      await expect(page.getByText("Золотая тренировка")).toBeVisible();
      await expectNoHorizontalOverflow(page, "Workout Detail: pre-screen");

      const startRequest = page.waitForRequest(
        (request) => request.url().endsWith("/api/v2/sessions/live") && request.method() === "POST",
      );
      const startResponse = page.waitForResponse(
        (response) => response.url().endsWith("/api/v2/sessions/live") && response.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Начать", exact: true }).click();
      const body = (await startRequest).postDataJSON();
      expect(body.workout_id).toBeGreaterThan(0);
      expect(body.plan_item_ids ?? []).toEqual([]);
      const response = await startResponse;
      expect(response.status()).toBe(200);
      const session = await response.json();
      expect(session.status).toBe("started");
      expect(session.title).toBe("Золотая тренировка");
      expect(session.blocks[0].targets).toHaveLength(2);

      await expect(page.getByText("Живая тренировка")).toBeVisible();
      await expectNoHorizontalOverflow(page, "Workout Detail: живая сессия");

      // Reload посреди сессии: активная сессия возобновляется, а не создаётся вторая.
      await page.reload({ waitUntil: "networkidle" });
      await expect(page.getByText("Живая тренировка")).toBeVisible();

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("«Записать» открывает форму записи задним числом с этой тренировкой", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, id + 5 + testInfo.retry, { theme });
      await page.getByTestId("my-workout-card").filter({ hasText: "Золотая тренировка" }).click();
      await page.getByTestId("workout-detail-log").click();

      await expect(page.getByTestId("journal-log-form")).toBeVisible();
      await expect(page.getByTestId("log-workout-select").locator("option:checked")).toHaveText("Золотая тренировка");
      await expect(page.getByTestId("log-exercise")).toHaveCount(1);
      await expectNoHorizontalOverflow(page, "Workout Detail: форма «Записать»");

      const setInputs = page.locator('[data-testid^="log-set-"]');
      await expect(setInputs).toHaveCount(2);
      await setInputs.nth(0).fill("8");
      await setInputs.nth(1).fill("6");
      await page.getByTestId("log-save").click();

      const card = page.locator(".history-card-clickable").filter({ hasText: "Записана задним числом" });
      await expect(card).toHaveCount(1);
      await expect(card).toContainText("8 · 6");

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
