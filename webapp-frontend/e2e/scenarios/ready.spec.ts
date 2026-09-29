import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py ready 900003 — одна прошлая тренировка 5 дней назад
// (старая схема: блоки Объём/Сила на резине), плана на неделю нет.
const TELEGRAM_ID = 900_003;

// Старый путь "Планы → Начать тренировку → Внести результат" (WorkoutScreen)
// убран из продукта в Checkpoint 5A (feat: remove legacy global workout entry
// points) — единственный вход в тренировку теперь карточки плана (см.
// first-workout.spec.ts, builder-execution.spec.ts). Возвращающийся
// пользователь видит: глобальной кнопки старта нет ни на «Главной», ни в
// «Планах», а прошлая тренировка доступна в «Журнале».
test("возвращающийся пользователь: нет глобального старта, прошлая тренировка — в Журнале", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);

  await expect(page.getByRole("button", { name: "Начать тренировку" })).toHaveCount(0);

  await page.getByRole("button", { name: "Планы" }).click();
  await expect(page.getByRole("heading", { name: "Мои тренировки" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Начать тренировку" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Начать", exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: "Журнал" }).click();
  await expect(page.getByText("Объём (резина): 10, 10, 10, максимум 11, следующая цель 11")).toBeVisible();
  await expect(page.getByText("Сила (резина): 3, 3, 3, 3, максимум 3, следующая цель 3")).toBeVisible();
  await expect(page.getByRole("button", { name: "✏️ Изменить" })).toHaveCount(1);

  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});
