import { expect, test } from "@playwright/test";
import { openAppAs } from "../fixtures/setup";

// Seed: journal_calendar 939951. Delay a real API response, preserving its body.
test("late post-write calendar refresh preserves the selected month's dots", async ({ page }) => {
  const { apiFailures, consoleErrors } = await openAppAs(page, 939951);
  await page.getByRole("button", { name: "Журнал", exact: true }).click();
  await expect(page.locator(".history-card-clickable")).toHaveCount(1);
  await page.locator(".journal-month-label").click();
  let release!: () => void;
  let captured!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  const received = new Promise<void>((resolve) => { captured = resolve; });
  let arm = true;
  await page.route("**/api/v2/journal/days?*", async (route) => {
    if (!arm) { await route.continue(); return; }
    arm = false;
    const response = await route.fetch();
    expect(response.ok()).toBeTruthy();
    captured();
    await held;
    await route.fulfill({ response });
  });
  await page.getByTestId("journal-log-button").click();
  await page.getByTestId("log-option-activity").click();
  await page.getByTestId("log-duration").fill("1:15");
  await page.getByTestId("log-save").click();
  await received;
  await expect(page.getByTestId("journal-log-sheet")).toHaveCount(0);
  await page.getByRole("button", { name: "Предыдущий месяц" }).click();
  const dots = page.locator('.journal-calendar-day[data-has-training="true"]');
  await expect(dots).toHaveCount(3);
  const dates = await dots.evaluateAll((elements) => elements.map((element) => element.getAttribute("data-date")));
  const delivered = page.waitForResponse((response) => response.url().includes("/journal/days?") && response.request().method() === "GET");
  release();
  await delivered;
  // Let React consume the released response before inspecting the calendar.
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  await expect(dots).toHaveCount(3);
  expect(await dots.evaluateAll((elements) => elements.map((element) => element.getAttribute("data-date")))).toEqual(dates);
  await expect(page.locator(".history-card-clickable")).toHaveCount(4);
  expect(apiFailures).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
