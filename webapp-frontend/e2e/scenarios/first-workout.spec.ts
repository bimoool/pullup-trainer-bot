import { expect, test } from "@playwright/test";

import { finishV2, noWakeLock, openPreScreen, playSetsV2 } from "../fixtures/builderFlow";
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

  // issue #305 (V5.6): замер онбординга M = 6 → уровень 1 (с помощью). Для рецепта не хватает R (способность
  // с объёмной резиной), объёмной резины и помощи в силовом блоке — пред-экран просит их, а не угадывает.
  await openPreScreen(page, PROGRAM);
  await expect(page.getByTestId("course-setup-required")).toBeVisible();
  await page.getByTestId("course-input-volume_capacity").fill("10");
  await page.getByTestId("course-volume-band-name").fill("Синяя");
  await page.getByTestId("course-strength-band-bodyweight").check();
  await page.getByTestId("course-setup-save").click();
  // R = 10 → A: 7/7/7/7+ (floor(0,7·10)), сила 5/5/5/5/5–8 без помощи.
  await expect(page.getByText("Блок 1: 7/7/7/7+")).toBeVisible();
  await expect(page.getByText("Блок 2: 5/5/5/5/5–8")).toBeVisible();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await expect(page.getByText("Живая тренировка")).toBeVisible();
  await expect(page.getByTestId("engine-target")).toContainText("Подход 1/4"); // #306: Live Engine v2
  await playSetsV2(page, ["10"]);
  await finishV2(page, { early: true });

  await expect(page.getByText("Тренировка завершена", { exact: true })).toBeVisible();
  // один из четырёх подходов объёма A (V5.6: 7/7/7/7+ — последний технический AMRAP)
  await expect(page.getByText(/— 1\/4/)).toBeVisible();
  // статус блока не только иконкой: скринридер слышит «не выполнено» (1 из 4 подходов)
  await expect(page.locator(".live-card-title").filter({ hasText: /— 1\/4/ }).locator(".vp-sr-only")).toHaveText(", не выполнено");

  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});
