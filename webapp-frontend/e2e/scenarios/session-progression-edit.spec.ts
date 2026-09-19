import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py v2_session_progression_edit 900012 — STEP-курс, одна
// сессия вчера (блок A 11/11/11+12макс, блок Б 4/4/4/4+4макс — те же числа,
// что уже доказаны в test_v2_live_session.py, см. докстринг сценария).
const TELEGRAM_ID = 900_012;

// Критерий готовности раздела 15, дословно: "Правка вчерашней сессии → лист
// preview с изменениями → Применить → target следующей сессии изменился;
// Оставить → не изменился". Preview не имеет побочных эффектов (см.
// tests/test_web/test_v2_progression_cascade.py), поэтому оба ветвления
// проверяются на ОДНОМ и том же исходном состоянии — сначала "Оставить"
// (цель не сдвинулась), потом "Применить" (цель сдвинулась) — не наоборот.
test("правка вчерашней v2-сессии: preview → Оставить не меняет цель, Применить меняет", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);

  await page.getByRole("button", { name: "Dashboard" }).click();
  await expect(page.getByText("Блок A — цель 10")).toBeVisible();

  async function openEditAndFillStrongerBlockA() {
    await page.getByRole("button", { name: "Журнал (v2)" }).click();
    await page.getByRole("button", { name: "Изменить" }).click();
    await page.getByLabel("Блок A, подход 1").fill("16");
    await page.getByLabel("Блок A, подход 2").fill("16");
    await page.getByLabel("Блок A, подход 3").fill("16");
    await page.getByLabel("Блок A, подход на максимум").fill("18");
    await page.getByRole("button", { name: "Предпросмотр" }).click();
    await expect(page.getByText(/block_a: \d+ → \d+/)).toBeVisible();
  }

  // Ветка "Оставить" — цель блока A не меняется.
  await openEditAndFillStrongerBlockA();
  await page.getByRole("button", { name: "Оставить" }).click();
  await page.getByRole("button", { name: "Назад" }).click();
  await expect(page.getByText("Блок A — цель 10")).toBeVisible();

  // Ветка "Применить" — тот же preview, на этот раз применяем.
  await openEditAndFillStrongerBlockA();
  await page.getByRole("button", { name: "Применить" }).click();
  await page.getByRole("button", { name: "Назад" }).click();
  await expect(page.getByText("Блок A — цель 10")).toHaveCount(0);

  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});
