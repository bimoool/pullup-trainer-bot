import { expect, test } from "@playwright/test";
import type { SessionResponseV2 } from "../../src/apiV2";
import { buildInitData, getTestBotToken } from "../fixtures/initData";
import { openAppAs } from "../fixtures/setup";

// Independent golden_journey users. Completed prior months also work on the first day of a month.
for (const [index, crossMonth] of [false, true].entries()) {
  test(`clone becomes visible (${crossMonth ? "month boundary" : "same month"})`, async ({ page }, testInfo) => {
    const id = 939_921 + index * 10 + testInfo.retry;
    const headers = { "X-Telegram-Init-Data": buildInitData({ id, firstName: "E2E" }, getTestBotToken()) };
    const now = new Date();
    const month = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 2, 1));
    const originalDate = crossMonth
      ? new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth() + 1, 0)).toISOString().slice(0, 10)
      : month.toISOString().slice(0, 7) + "-10";
    const copyDate = crossMonth
      ? new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth() + 1, 1)).toISOString().slice(0, 10)
      : month.toISOString().slice(0, 7) + "-11";
    await openAppAs(page, id);
    await page.getByRole("button", { name: "Журнал", exact: true }).click();
    await page.getByTestId("journal-log-button").click();
    await page.getByTestId("log-option-workout").click();
    await page.getByTestId("log-workout-select").selectOption({ label: "Золотая тренировка" });
    await page.getByTestId("log-date").fill(originalDate);
    await page.locator('[data-testid^="log-set-"]').nth(0).fill("8");
    await page.locator('[data-testid^="log-set-"]').nth(1).fill("7");
    await page.getByTestId("log-save").click();
    const cards = page.locator(".history-card-clickable");
    await expect(cards).toHaveCount(1);
    const before = await page.request.get("/api/v2/sessions?status=completed&limit=200", { headers });
    expect(before.ok()).toBeTruthy();
    const original = (await before.json()).sessions[0];
    await page.locator(".journal-month-label").click();
    await page.locator(`button[data-date="${originalDate}"]`).click();
    await expect(page.locator(`button[data-date="${originalDate}"]`)).toHaveAttribute("aria-pressed", "true");
    await cards.click();
    await page.getByTestId("journal-sheet-clone").click();
    await page.getByLabel("Дата новой записи").fill(copyDate);
    const cloned = page.waitForResponse((response) => response.url().endsWith(`/sessions/${original.id}/clone`) && response.request().method() === "POST");
    await page.getByRole("button", { name: "Создать копию", exact: true }).click();
    expect((await cloned).ok()).toBeTruthy();
    await expect(page.getByTestId("journal-clone-form")).toHaveCount(0);
    await expect(cards).toHaveCount(crossMonth ? 1 : 2);
    await expect(page.locator(`button[data-date="${copyDate}"]`)).toHaveAttribute("data-has-training", "true");
    await expect(page.locator('.journal-calendar-day[aria-pressed="true"]')).toHaveCount(0);
    const after = await page.request.get("/api/v2/sessions?status=completed&limit=200", { headers });
    expect(after.ok()).toBeTruthy();
    const sessions = (await after.json()).sessions;
    expect(sessions).toHaveLength(2);
    expect(sessions.find((session: { id: number }) => session.id === original.id)).toEqual(original);
    const copy = sessions.find((session: { id: number }) => session.id !== original.id);
    expect(copy.source).toBe("backdated");
    expect(copy.plan_item_id).toBeNull();
    expect(copy.progression_result).toBeNull();
    expect(copy.id).not.toBe(original.id);
    expect(new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Moscow" }).format(new Date(copy.performed_at))).toBe(copyDate);
    const facts = (session: SessionResponseV2) => session.blocks.map((block) => ({
      order: block.order_index, exercise: block.exercise_id, protocol: block.protocol_type,
      result: block.result, targets: block.set_targets,
      logs: block.set_logs.map((log) => ({
        number: log.set_number, value: log.value, unit: log.unit, effort: log.effort, note: log.note,
      })),
    }));
    expect(facts(copy)).toEqual(facts(original));
    await page.locator(`button[data-date="${copyDate}"]`).click();
    await expect(cards).toHaveCount(1);
  });
}
