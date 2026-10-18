import { expect, test, type Page } from "@playwright/test";

import { buildInitData, getTestBotToken } from "../fixtures/initData";
import { openAppAs } from "../fixtures/setup";

/**
 * UX-03 (executor C): одна длительность занятия (активное время движка) в Итоге, деталях и карточке Журнала,
 * минуты Аналитики считаются от того же duration_seconds. Ни «0:00», ни «0 мин» у занятия с внесённым подходом.
 * Сид: scripts/e2e_seed.py live_engine 930643/930644 (два пользователя: обычное завершение и досрочное).
 */
test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
test.setTimeout(120_000);

const ID_NATURAL = 930_643;
const ID_EARLY = 930_644;

function expectedLabel(seconds: number): string {
  return seconds < 60 ? `${seconds} с` : `${Math.round(seconds / 60)} мин`;
}

async function api<T>(page: Page, telegramId: number, path: string): Promise<T> {
  const initData = buildInitData({ id: telegramId, firstName: "E2E" }, getTestBotToken());
  const response = await page.request.get(path, { headers: { "X-Telegram-Init-Data": initData } });
  return (await response.json()) as T;
}

async function startPlanned(page: Page, title: string) {
  await page.getByRole("button", { name: "Планы" }).click();
  const group = page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${title}`) });
  await group.getByRole("button", { name: /^Начать: / }).first().click();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await expect(page.getByText("Живая тренировка")).toBeVisible();
}

async function checkAllPlaces(page: Page, telegramId: number, summaryText: string) {
  const completed = await api<{ sessions: { id: number; duration_seconds: number | null }[] }>(
    page, telegramId, "/api/v2/sessions?status=completed",
  );
  const seconds = completed.sessions[0].duration_seconds;
  expect(seconds).not.toBeNull();
  expect(seconds as number).toBeGreaterThan(0);
  const label = expectedLabel(seconds as number);
  expect(summaryText).toBe(label); // Итог

  await page.getByRole("button", { name: "Журнал" }).click();
  const card = page.getByTestId("journal-card").first();
  await expect(card.getByTestId("journal-card-duration")).toHaveText(label); // карточка Журнала
  await card.click();
  await page.getByRole("button", { name: "Открыть", exact: true }).click();
  await expect(page.getByTestId("journal-activity-duration")).toHaveText(`Длительность: ${label}`); // деталь
  await expect(page.locator("body")).not.toContainText("0:00");

  const analytics = await api<{ metrics: { total_minutes: number } }>(page, telegramId, "/api/v2/analytics/training");
  expect(analytics.metrics.total_minutes).toBe(Math.floor(((seconds as number) + 30) / 60)); // round half up
}

test("завершение до конца: Итог, карточка и деталь Журнала, минуты Аналитики — одно значение", async ({ page }) => {
  await openAppAs(page, ID_NATURAL);
  await startPlanned(page, "Движок: блоки");
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл");
  await page.getByLabel("Результат подхода").fill("3");
  await page.getByTestId("engine-submit").click();
  await expect(page.getByTestId("engine-complete")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("engine-save").click();
  await expect(page.getByTestId("summary-duration")).toBeVisible();
  const summaryText = (await page.getByTestId("summary-duration").innerText()).trim();
  await page.getByRole("button", { name: /Готово|Закрыть|На главную/ }).first().click();
  await checkAllPlaces(page, ID_NATURAL, summaryText);
});

test("досрочное завершение после подхода: то же значение везде, не «0:00»", async ({ page }) => {
  await openAppAs(page, ID_EARLY);
  await startPlanned(page, "Движок: подходы");
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл", { timeout: 10_000 });
  await page.getByLabel("Результат подхода").fill("5");
  await page.getByTestId("engine-submit").click();
  await page.getByTestId("engine-finish").click();
  await page.getByTestId("engine-finish-confirm").click();
  await expect(page.getByTestId("summary-duration")).toBeVisible({ timeout: 15_000 });
  const summaryText = (await page.getByTestId("summary-duration").innerText()).trim();
  await page.getByRole("button", { name: /Готово|Закрыть|На главную/ }).first().click();
  await checkAllPlaces(page, ID_EARLY, summaryText);
});
