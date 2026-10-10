import { expect, test } from "@playwright/test";

import { noWakeLock, playSets, startWorkout } from "../fixtures/builderFlow";
import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py first_workout 900002 — анкета пройдена, тренировок и
// плана ещё нет; в каталоге «Главной» есть STEP-курс «Первая тренировка
// (E2E)» (ProgramItem на оба блока), пользователь его ещё не включал.
const TELEGRAM_ID = 900_002;
const PROGRAM = "Первая тренировка";

// Старый путь (Dashboard → подтверждение снаряда → форма, issue #175) убран
// вместе с глобальным стартом (Checkpoint 5A): первая тренировка теперь —
// «Главная» → курс → «Добавить в план» → карточка в «Планах» → «Начать» →
// живая тренировка → «Завершить» → итог.
test("первая тренировка: курс из каталога → в план → живая тренировка → итог", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);
  page.on("dialog", (dialog) => void dialog.accept());

  // Глобальной кнопки старта нет — только курс в каталоге.
  await expect(page.getByRole("button", { name: "Начать тренировку" })).toHaveCount(0);
  await page.getByRole("button", { name: PROGRAM }).click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await expect(page.getByRole("button", { name: "В плане", exact: true })).toBeVisible();

  await startWorkout(page, PROGRAM);
  await playSets(page, ["10"]);
  await page.getByRole("button", { name: "Завершить" }).click();
  await page.getByRole("button", { name: "Сохранить и завершить", exact: true }).click();

  await expect(page.getByText("Тренировка завершена", { exact: true })).toBeVisible();
  // один из четырёх подходов блока A: 3 рабочих + подход на максимум (#305, OD-3 решён: включать)
  await expect(page.getByText(/— 1\/4/)).toBeVisible();
  // статус блока не только иконкой: скринридер слышит «не выполнено» (1 из 4 подходов)
  await expect(page.locator(".live-card-title").filter({ hasText: /— 1\/4/ }).locator(".vp-sr-only")).toHaveText(", не выполнено");

  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});
