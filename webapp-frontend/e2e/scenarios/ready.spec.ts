import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py ready 900003 — одна прошлая тренировка 5 дней назад,
// снаряд обоих блоков уже BAND (см. scripts/e2e_seed.py::seed_ready).
const TELEGRAM_ID = 900_003;

test("обычный день тренировки: полный путь ввода результата до записи", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);

  // Волна 5b (issue #183) — стартовый экран теперь "Главная" (каталог,
  // пока пустой), Dashboard целиком переехал на вкладку "Планы".
  await page.getByRole("button", { name: "Планы" }).click();

  // Dashboard (issue #175) — сводка вместо сразу открытой формы тренировки
  // (product-reference skill, референс — Crimpd).
  await expect(page.getByText("Готов к тренировке.")).toBeVisible();
  await page.getByRole("button", { name: "Начать тренировку" }).click();

  await expect(page.getByText("Текущий план")).toBeVisible();
  await page.getByRole("button", { name: "📝 Внести результат тренировки" }).click();

  // work_sets_a=3/work_sets_b=4 для этого сидирования (подтверждено
  // tests/test_web/test_workout.py::test_plan_ready_shows_target_and_equipment)
  // — те же значения, что и в прошлой тренировке, чтобы гарантированно не
  // задеть detect_anomalies (резкий скачок относительно среднего) и дойти
  // до записи без промежуточного экрана подтверждения аномалии.
  for (const n of [1, 2, 3]) {
    await page.getByLabel(`Блок A, подход ${n}`).fill("10");
  }
  await page.getByLabel("Блок A, подход на максимум").fill("11");

  for (const n of [1, 2, 3, 4]) {
    await page.getByLabel(`Блок B, подход ${n}`).fill("3");
  }
  await page.getByLabel("Блок B, подход на максимум").fill("3");

  await page.getByRole("button", { name: "Записать тренировку" }).click();

  await expect(page.getByText("Тренировка записана")).toBeVisible();

  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});
