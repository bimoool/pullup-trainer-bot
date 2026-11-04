import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// Browser startup regression: API response is fixed so the test isolates the optional read-cache.
// Blocking localStorage must not stop the server-backed Mini App before React mounts.
test("Mini App starts when browser policy denies localStorage", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() { throw new DOMException("Storage blocked by browser policy", "SecurityError"); },
    });
  });
  await page.route("**/api/hello", (route) => route.fulfill({
    json: {
      name: "E2E", onboarding_step: "not_registered", readiness_status: null,
      days_since_last_workout: null, is_admin: false,
    },
  }));
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await openAppAs(page, 900_001);
  await expect(page.getByLabel("Сколько подтягиваний вышло?")).toBeVisible();
  expect(pageErrors).toEqual([]);
});
