import { expect, test } from "@playwright/test";

import { finishV2, noWakeLock, playSetsV2 } from "../fixtures/builderFlow";
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

  // issue #306 (Live Engine v2): упражнения сменяются сами по дедлайну отдыха блока; здесь ожидание
  // сокращается «Начать сейчас». Упражнения 1 и 2 из 3, третье не трогаем — завершаем досрочно.
  await expect(page.getByTestId("engine-target")).toContainText("Цель:");
  await playSetsV2(page, ["10", "10"]);
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых");
  await expect(page.getByTestId("engine-next-block")).toBeVisible();
  await finishV2(page, { early: true });

  await expect(page.getByText("Тренировка завершена").first()).toBeVisible();
  await expect(page.getByText(/— 1\/1/)).toHaveCount(2); // два выполненных упражнения
  await expect(page.getByText(/— 0\/1/)).toHaveCount(1); // третье осталось нетронутым
  await expect(page.getByText("Не выполнено — осталось в плане.")).toBeVisible();

  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});
