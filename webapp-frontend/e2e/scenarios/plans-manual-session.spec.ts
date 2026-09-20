import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py plan_week_manual_session 900017 — две manual PlanItem
// (Планка/среда, Отжимания/пятница), program_inclusion_id=NULL, без единой
// Program/ProgramInclusion вообще. НЕ admin-only.
const TELEGRAM_ID = 900_017;

test("«Планы» → manual «Планка»/«Отжимания» → Start без ProgramInclusion → Complete → Summary", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);

  await page.getByRole("button", { name: "Планы" }).click();
  await expect(page.getByText("Среда")).toBeVisible();
  await expect(page.getByText("Пятница")).toBeVisible();
  await expect(page.getByText("Планка", { exact: true })).toBeVisible();
  await expect(page.getByText("Отжимания", { exact: true })).toBeVisible();

  // --- Планка: Start без всякого ProgramInclusion/STEP readiness ---
  const startButtons = page.getByRole("button", { name: "Начать", exact: true });
  await startButtons.first().click();
  await page.waitForTimeout(800);

  // manual pre-screen НЕ должен показать no_course/blocked/needs_assessment
  await expect(page.getByText("Нет активного курса")).toHaveCount(0);
  await expect(page.getByText("Ещё рано для следующей тренировки")).toHaveCount(0);
  await expect(page.getByText("Был долгий перерыв")).toHaveCount(0);
  await expect(page.getByText("Планка")).toBeVisible();

  const startResponsePromise = page.waitForResponse(
    (response) => response.url().includes("/api/v2/sessions/live") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  const started = await startResponsePromise.then((r) => r.json());
  expect(started.blocks).toHaveLength(1);
  const plankSessionId = started.id;

  // --- Реальное имя, не "Упражнение #id", единица "s", без "Цель: 0" ---
  await page.waitForTimeout(800);
  await expect(page.getByText(/^Упражнение #/)).toHaveCount(0);
  await expect(page.getByText("Планка", { exact: false })).toBeVisible();
  await expect(page.getByText(/Цель: 0/)).toHaveCount(0);

  await page.getByRole("button", { name: "Готов", exact: true }).click();
  await page.waitForSelector("text=Пошёл", { timeout: 8000 });
  await page.getByLabel("Результат").fill("30");
  const setResponsePromise = page.waitForResponse(
    (response) => response.url().includes("sets:batch") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Готово", exact: true }).click();
  await setResponsePromise;
  await page.waitForTimeout(600);

  // --- Reload посреди STARTED manual-сессии ---
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(1000);
  await expect(page.getByText("Живая тренировка")).toBeVisible();
  await expect(page.getByText(/^Упражнение #/)).toHaveCount(0);

  // --- Завершить Планку ---
  page.on("dialog", (dialog) => dialog.accept());
  const completeResponsePromise = page.waitForResponse(
    (response) => response.url().includes("/complete") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Завершить", exact: true }).click();
  const completed = await completeResponsePromise.then((r) => r.json());
  expect(completed.id).toBe(plankSessionId);
  expect(completed.status).toBe("completed");

  await page.waitForTimeout(600);
  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  await expect(page.getByText(/^Упражнение #/)).toHaveCount(0);
  await expect(page.getByText(/30/)).toBeVisible();

  expect(apiFailures).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
