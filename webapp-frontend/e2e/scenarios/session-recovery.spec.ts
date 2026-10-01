import { expect, test } from "@playwright/test";

import { clickAndSync, noWakeLock, playSets } from "../fixtures/builderFlow";
import { openAppAs } from "../fixtures/setup";

// Восстановление активной тренировки после фона и повторного открытия
// (issue #246). scripts/e2e_seed.py session_recovery 930002: Workout
// «Тренировка восстановления», reps 3 x 8, отдых 60 с. Admin не нужен —
// путь обычного пользователя: Планы → Начать.
const TITLE = "Тренировка восстановления";

test.setTimeout(120_000);

/** Остаток таймера, показанный на экране, в секундах ("1:05" → 65). */
async function shownSeconds(page: import("@playwright/test").Page): Promise<number> {
  const text = (await page.locator(".timer-duration-label").first().innerText()).trim();
  const [minutes, seconds] = text.split(":").map(Number);
  return minutes * 60 + seconds;
}

test("активная тренировка: фон/передний план, reload — та же сессия, подходы не дублируются, таймер по часам", async ({
  page,
}, testInfo) => {
  // Playwright retry shares the CI database with the first attempt. Each
  // attempt gets a separately seeded user so a failed attempt cannot leave an
  // active session or move the workout out of the free pool for the retry.
  const telegramId = 930_002 + testInfo.retry;
  page.on("dialog", (dialog) => void dialog.accept());
  const { consoleErrors, apiFailures } = await openAppAs(page, telegramId);

  // --- старт из свободного пула «Планов» ---
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

  // --- прогресс: подход 1 записан, идёт отдых ---
  await playSets(page, ["8"], false);
  await expect(page.getByRole("heading", { name: "Отдых", exact: true })).toBeVisible();
  const restBefore = await shownSeconds(page);
  expect(restBefore).toBeGreaterThan(0);
  expect(restBefore).toBeLessThanOrEqual(60);

  // --- фон → передний план: событие visibilitychange, таймер не сбрасывается ---
  await page.waitForTimeout(2500);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.waitForTimeout(3000); // "в фоне" проходит время
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(page.getByRole("heading", { name: "Отдых", exact: true })).toBeVisible();
  const restForeground = await shownSeconds(page);
  expect(restForeground).toBeLessThan(restBefore - 3); // прошло ≥ 5 с реального времени

  // --- повторное открытие (reload): та же сессия, не пустой и не вечный «Загрузка» ---
  const resumeRequests: number[] = [];
  page.on("response", (response) => {
    if (response.url().includes("/api/v2/sessions/live") && response.request().method() === "POST") {
      resumeRequests.push(response.status());
    }
  });
  await page.reload();
  await expect(page.getByText("Живая тренировка")).toBeVisible();
  await expect(page.getByText("Загрузка…")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Отдых", exact: true })).toBeVisible();
  expect(resumeRequests).toEqual([]); // вторая сессия не создавалась

  // Таймер продолжил с того места, а не начался заново с 60 с.
  const restAfterReload = await shownSeconds(page);
  expect(restAfterReload).toBeLessThanOrEqual(restForeground);
  expect(restAfterReload).toBeLessThan(restBefore - 3);

  // --- подходы не потеряны и не задвоены: продолжаем с подхода 2 ---
  await expect(page.getByText(/Подход 2\/3/)).toBeVisible();
  // Действие после reload уходит в ту же сессию, что была создана при старте.
  await clickAndSync(page, "Пропустить отдых", `/api/v2/sessions/live/${sessionId}/phase/next`);
  await playSets(page, ["7", "6"]);
  await clickAndSync(page, "Завершить", "/complete");
  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  await expect(page.getByText("Подход 1: 8 повт.")).toBeVisible();
  await expect(page.getByText("Подход 2: 7 повт.")).toBeVisible();
  await expect(page.getByText("Подход 3: 6 повт.")).toBeVisible();
  await expect(page.getByText(/Подход 4/)).toHaveCount(0);

  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});
