import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py first_workout 900002 — анкета пройдена (подписка
// есть), ни одной тренировки ещё не было.
const TELEGRAM_ID = 900_002;

test("первая тренировка (issue #123): нет тупиковых кнопок бэкдейта/свободных подтягиваний", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);

  await expect(
    page.getByText("Это твоя первая тренировка — замер и выбор снаряда пока доступны только в боте."),
  ).toBeVisible();

  // Регрессия на реальный баг issue #123: на этом статусе снаряд ни для
  // одного блока ещё не назначен — до фикса эти две кнопки были видны и
  // вели в тупик (бэкдейт подставлял резину-заглушку, которой физически
  // нет, сохранить результат было невозможно). NO_EQUIPMENT_YET_STATUSES в
  // WorkoutScreen.tsx теперь прячет обе кнопки на этом статусе.
  await expect(page.getByRole("button", { name: "🔁 Внести пропущенную тренировку" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "➕ Внести свободные подтягивания" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Открыть в боте" })).toBeVisible();

  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});
