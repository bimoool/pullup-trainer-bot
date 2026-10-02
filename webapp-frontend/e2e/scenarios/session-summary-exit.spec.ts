import { expect, test } from "@playwright/test";

import { noWakeLock, playSets } from "../fixtures/builderFlow";
import { openAppAs } from "../fixtures/setup";
import { isTelegramBackButtonVisible, pressTelegramBackButton } from "../fixtures/telegramMock";

// Выход из Summary после живой сессии (issue #253, QA §5): ни пустого, ни
// устаревшего экрана. scripts/e2e_seed.py session_recovery 930006: Workout
// «Тренировка восстановления», reps 3 x 8. Путь: Планы → Начать → подход →
// Завершить → Summary → Закрыть.
const TITLE = "Тренировка восстановления";

test.setTimeout(120_000);

test("Summary: BackButton не воскрешает сессию, «Закрыть» ведёт на живой экран, повторный вход не возвращает завершённую", async ({
  page,
}, testInfo) => {
  // Retry делит БД с первой попыткой — отдельный посеянный пользователь на попытку.
  const telegramId = 930_006 + testInfo.retry;
  page.on("dialog", (dialog) => void dialog.accept());
  const completeRequests: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/complete")) {
      completeRequests.push(request.url());
    }
  });
  const { consoleErrors, apiFailures } = await openAppAs(page, telegramId, { backButton: true });

  await page.getByTestId("my-workout-card").filter({ hasText: TITLE }).click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await page.getByRole("button", { name: "Свободный пул" }).click();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  const startGroup = () => page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${TITLE}`) });
  await startGroup().getByRole("button", { name: /^Начать: / }).click();
  const started = page.waitForResponse((r) => r.url().includes("/api/v2/sessions/live") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  const sessionId = ((await (await started).json()) as { id: number }).id;
  await expect(page.getByText("Живая тренировка")).toBeVisible();

  await playSets(page, ["8"], false);
  const complete = page.waitForResponse((r) => r.url().includes(`/api/v2/sessions/live/${sessionId}/complete`));
  await page.getByRole("button", { name: "Завершить", exact: true }).click();
  await page.getByRole("button", { name: "Сохранить и завершить", exact: true }).click();
  expect((await complete).status()).toBe(200);
  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  expect(completeRequests).toHaveLength(1);

  // BackButton на Summary скрыт; даже нажатие ничего не шлёт и не открывает live.
  expect(await isTelegramBackButtonVisible(page)).toBe(false);
  await pressTelegramBackButton(page);
  await page.waitForTimeout(500);
  expect(completeRequests).toHaveLength(1);
  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  await expect(page.getByText("Живая тренировка")).toHaveCount(0);

  // «Закрыть» — реальный экран с контентом, не пустой.
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  await expect(page.getByText("Тренировка завершена")).toHaveCount(0);
  await expect(page.getByText("Живая тренировка")).toHaveCount(0);
  await expect(page.locator("#root")).not.toBeEmpty();
  await expect(page.getByRole("button", { name: "Планы" })).toBeVisible();
  await expect(page.getByText(/ошибка/i)).toHaveCount(0);
  await page.getByRole("button", { name: "Планы" }).click();
  await expect(page.getByText("Свободный пул")).toBeVisible();

  // Повторное открытие — завершённая сессия не оживает как активная.
  if ((await startGroup().count()) > 0) {
    await startGroup().getByRole("button", { name: /^Начать: / }).click();
    await expect(page.getByText("Живая тренировка")).toHaveCount(0);
  }
  await page.reload();
  await expect(page.getByText("Живая тренировка")).toHaveCount(0);
  await expect(page.getByText("Тренировка завершена")).toHaveCount(0);
  expect(completeRequests).toHaveLength(1);

  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});
