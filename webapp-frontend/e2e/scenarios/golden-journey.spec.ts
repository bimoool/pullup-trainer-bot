import { expect, test } from "@playwright/test";

import { clickAndSync, noWakeLock, playSets } from "../fixtures/builderFlow";
import { openAppAs } from "../fixtures/setup";

// Golden Journey (issue #221) — сквозной путь вернувшегося пользователя по
// ТЕКУЩЕМУ продукту: Главная → Программы → Мои тренировки → в план → старт →
// reps → Summary → Аналитика → Журнал → безопасное удаление.
//
// Остальные инварианты держат узкие современные сценарии (не дублируем):
//   home-discovery      — Главная/Мои тренировки/создание, 320 и 390 px
//   builder-execution   — reps / time / max / interval / смешанная / дубли
//   session-offline     — офлайн-подходы и синхронизация после reconnect
//   journal-v2          — карточки всех протоколов, детали, пагинация, 409/404
//   analytics-v2        — активность и панели протоколов
//   plans-*, ready, first-workout, not-onboarded — планы и статусы
//
// scripts/e2e_seed.py golden_journey 930001.
const TELEGRAM_ID = 930_001;
const TITLE = "Золотая тренировка";

test.setTimeout(120_000);

test("Golden Journey: Главная → в план → тренировка → Summary → Аналитика → Журнал → удаление", async ({ page }) => {
  page.on("dialog", (dialog) => void dialog.accept());
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);

  // --- Главная: Программы (детали и обратно) и Мои тренировки ---
  await expect(page.locator(".plan-title")).toHaveText("Главная");
  await page.locator(".program-card-button").first().click();
  await expect(page.getByRole("button", { name: /Добавить в план|В плане/ })).toBeVisible();
  await page.getByRole("button", { name: "← Назад" }).click();
  const card = page.getByTestId("my-workout-card").filter({ hasText: TITLE });
  await expect(card).toContainText("1 упражнение");

  // --- Мою тренировку в план (свободный пул текущей недели) ---
  await card.click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await page.getByRole("button", { name: "Свободный пул" }).click();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  const group = page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${TITLE}`) });
  await expect(group).toBeVisible(); // приземлились на «Планах»

  // --- Старт → reps (2 подхода) → Summary ---
  await group.getByRole("button", { name: "Начать", exact: true }).click();
  await page.getByRole("button", { name: "Начать", exact: true }).click(); // SessionPreScreen
  await expect(page.getByText("Живая тренировка")).toBeVisible();
  await expect(page.getByText(/Подход 1\/2 · Цель: 8 повт\./)).toBeVisible();
  await playSets(page, ["8", "7"]);
  await page.getByRole("button", { name: "Завершить", exact: true }).click();
  await clickAndSync(page, "Сохранить и завершить", "/complete");
  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  await expect(page.getByText("Подход 1: 8 повт.")).toBeVisible();
  await page.getByRole("button", { name: "Закрыть" }).click();

  // --- Аналитика видит тренировку ---
  await page.getByRole("button", { name: "Аналитика" }).click();
  const stat = page.locator(".analytics-stat").filter({ hasText: "Тренировок за 30 дней" });
  await expect(stat).toContainText("1");
  await expect(page.getByRole("button", { name: "Подтягивания" })).toBeVisible();

  // --- Журнал: карточка, детали, безопасное удаление ---
  await page.getByRole("button", { name: "Журнал" }).click();
  const entry = page.locator(".history-card").filter({ hasText: TITLE });
  await expect(entry.getByText("8 · 7", { exact: true })).toBeVisible();
  await entry.click();
  await expect(page.getByText("Факт: 8 · 7")).toBeVisible();
  await page.getByRole("button", { name: /Удалить/ }).click();
  await expect(page.locator(".history-card").filter({ hasText: TITLE })).toHaveCount(0);

  // Определение Workout пережило удаление сессии: снова на Главной.
  await page.getByRole("button", { name: "Главная" }).click();
  await expect(page.getByTestId("my-workout-card").filter({ hasText: TITLE })).toBeVisible();

  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});
