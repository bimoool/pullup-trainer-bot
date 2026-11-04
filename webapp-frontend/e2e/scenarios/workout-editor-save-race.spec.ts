import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// Separate golden_journey users (939901/939902) keep retries independent.
test("saving a workout cannot open a plan sheet that the save callback then closes", async ({ page }, testInfo) => {
  await openAppAs(page, 939_901 + testInfo.retry);
  await page.getByTestId("my-workout-card").filter({ hasText: "Золотая тренировка" }).click();
  await page.getByRole("button", { name: "Изменить", exact: true }).click();
  const addToPlan = page.getByRole("button", { name: "Добавить в план", exact: true });
  await expect(addToPlan).toBeEnabled();

  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => { release = resolve; });
  let requestStarted: () => void = () => {};
  const started = new Promise<void>((resolve) => { requestStarted = resolve; });
  await page.route("**/api/v2/workouts/*", async (route) => {
    if (route.request().method() === "PATCH") {
      requestStarted();
      await gate;
    }
    await route.continue();
  });
  try {
    await page.getByRole("button", { name: "Сохранить", exact: true }).click();
    await started;
    await expect(addToPlan).toBeDisabled();
    await expect(page.getByTestId("form-sheet")).toHaveCount(0);
  } finally {
    release();
  }

  await expect(page.getByTestId("workout-detail")).toBeVisible();
  await page.getByTestId("workout-detail-add-to-plan").click();
  await page.getByRole("button", { name: "Ср", exact: true }).click();
  await expect(page.getByTestId("form-sheet")).toBeVisible();
  await expect(page.getByTestId("form-sheet").getByRole("button", { name: "Добавить", exact: true })).toBeEnabled();
});
