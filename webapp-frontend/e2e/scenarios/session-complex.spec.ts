import { expect, test } from "@playwright/test";

import { noWakeLock } from "../fixtures/builderFlow";
import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py v2_session_complex 900011 — Program без стратегии +
// Complex из 3 упражнений по 1 подходу каждое, один PlanItem(complex_id=...)
// в текущей неделе плана.
const TELEGRAM_ID = 900_011;

// Критерий готовности раздела 15, дословно: "Комплекс из 3: сделал 2,
// завершил — в плане закрыты 2 PlanItem, третий на месте". Комплекс
// раскладывается в 3 отдельных блока сессии — каждый со своим exercise_id
// (app.services.live_session._resolve_complex_blocks), "закрыт"/"на месте"
// здесь проверяется на итоговом экране (план vs факт по блокам), не через
// отдельный API — эта волна не помечает ComplexItem/PlanItem статусом
// "выполнено" в БД, см. докстринг SessionSummaryScreen.tsx.
test("live-сессия (v2): комплекс из 3 упражнений, завершил после двух", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);
  page.on("dialog", (dialog) => void dialog.accept());

  // Комплекс запускается из «Планы» (карточка в текущей неделе) → пред-экран
  // → «Начать»; admin-вкладка «Dashboard» (лаба) для этого больше не нужна.
  await page.getByRole("button", { name: "Планы" }).click();
  await page.getByRole("button", { name: "Начать" }).click();
  await page.getByRole("button", { name: "Начать" }).click();

  // Упражнение 1 из 3.
  await page.getByRole("button", { name: "Готов" }).click();
  await expect(page.getByRole("heading", { name: "Пошёл", exact: true })).toBeVisible();
  await page.getByLabel("Результат").fill("10");
  await page.getByRole("button", { name: "Готово" }).click();

  // Один подход на упражнение -> сразу get_ready следующего упражнения
  // (next_phase: "последний подход НЕпоследнего блока -> get_ready
  // следующего блока", без фазы "Отдых").
  await expect(page.getByRole("heading", { name: "Приготовься", exact: true })).toBeVisible();

  // Упражнение 2 из 3.
  await page.getByRole("button", { name: "Готов" }).click();
  await expect(page.getByRole("heading", { name: "Пошёл", exact: true })).toBeVisible();
  await page.getByLabel("Результат").fill("10");
  await page.getByRole("button", { name: "Готово" }).click();

  // Упражнение 3 не трогаем — завершаем сессию досрочно.
  await expect(page.getByRole("heading", { name: "Приготовься", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Завершить" }).click();

  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  await expect(page.getByText(/— 1\/1/)).toHaveCount(2); // два выполненных упражнения
  await expect(page.getByText(/— 0\/1/)).toHaveCount(1); // третье осталось нетронутым
  await expect(page.getByText("Не выполнено — осталось в плане.")).toBeVisible();

  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});
