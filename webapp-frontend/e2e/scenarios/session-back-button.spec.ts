import { expect, test } from "@playwright/test";

import { noWakeLock, playSets } from "../fixtures/builderFlow";
import { openAppAs } from "../fixtures/setup";
import { isTelegramBackButtonVisible, pressTelegramBackButton } from "../fixtures/telegramMock";

// Telegram BackButton во время живой тренировки (issue #249): случайное
// «назад» не должно молча терять активную сессию. scripts/e2e_seed.py
// session_recovery 930004: Workout «Тренировка восстановления», reps 3 x 8,
// отдых 60 с. Путь обычного пользователя: Планы → Начать.
const TITLE = "Тренировка восстановления";
const CONFIRM_TEXT = "Закончить сессию?";

test.setTimeout(120_000);

async function startSetOneRecorded(page: import("@playwright/test").Page): Promise<number> {
  await page.getByTestId("my-workout-card").filter({ hasText: TITLE }).click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await page.getByRole("button", { name: "Свободный пул" }).click();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  const group = page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${TITLE}`) });
  await group.getByRole("button", { name: "Начать", exact: true }).click();

  const started = page.waitForResponse((r) => r.url().includes("/api/v2/sessions/live") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Начать", exact: true }).click(); // SessionPreScreen
  const sessionId = ((await (await started).json()) as { id: number }).id;
  await expect(page.getByText("Живая тренировка")).toBeVisible();

  await playSets(page, ["8"], false);
  await expect(page.getByRole("heading", { name: "Отдых", exact: true })).toBeVisible();
  return sessionId;
}

test("BackButton: отмена подтверждения оставляет ту же сессию, подход сохранён; подтверждение завершает ровно один раз", async ({
  page,
}, testInfo) => {
  // Retry делит БД с первой попыткой — отдельный посеянный пользователь на попытку.
  const telegramId = 930_004 + testInfo.retry;
  const dialogs: string[] = [];
  let answer = false;
  page.on("dialog", (dialog) => {
    dialogs.push(dialog.message());
    void (answer ? dialog.accept() : dialog.dismiss());
  });
  const completeRequests: string[] = [];
  const liveStarts: string[] = [];
  page.on("request", (request) => {
    if (request.method() !== "POST") {
      return;
    }
    if (request.url().includes("/complete")) {
      completeRequests.push(request.url());
    }
    if (request.url().endsWith("/api/v2/sessions/live")) {
      liveStarts.push(request.url());
    }
  });
  const { consoleErrors, apiFailures } = await openAppAs(page, telegramId, { backButton: true });

  const sessionId = await startSetOneRecorded(page);
  expect(await isTelegramBackButtonVisible(page)).toBe(true);
  liveStarts.length = 0;

  // --- отмена: диалог показан, сессия жива, ничего не завершено ---
  await pressTelegramBackButton(page);
  await expect.poll(() => dialogs.length).toBe(1);
  expect(dialogs[0]).toContain(CONFIRM_TEXT);
  await expect(page.getByText("Живая тренировка")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Отдых", exact: true })).toBeVisible();
  await expect(page.getByText("Тренировка завершена")).toHaveCount(0);
  expect(completeRequests).toEqual([]);

  // Та же сессия возобновляется после reload, подход 1 на месте, новая не создана.
  await page.reload();
  await expect(page.getByText("Живая тренировка")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Отдых", exact: true })).toBeVisible();
  expect(liveStarts).toEqual([]);
  expect(completeRequests).toEqual([]);

  // --- подтверждение: завершается ровно один раз, даже при повторных нажатиях ---
  answer = true;
  const complete = page.waitForResponse((r) => r.url().includes(`/api/v2/sessions/live/${sessionId}/complete`));
  await pressTelegramBackButton(page);
  await pressTelegramBackButton(page);
  expect((await complete).status()).toBe(200);
  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  await expect(page.getByText("Подход 1: 8 повт.")).toBeVisible();
  await expect(page.getByText(/Подход 2/)).toHaveCount(0);

  // Нажатие после завершения ничего не отправляет и не меняет итог.
  await pressTelegramBackButton(page);
  await page.waitForTimeout(500);
  expect(completeRequests).toHaveLength(1);
  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  await expect(page.getByText("Подход 1: 8 повт.")).toBeVisible();

  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});
