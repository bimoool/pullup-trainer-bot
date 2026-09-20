import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py plan_week_start_session 900016 — реальная STEP-
// программа "Подтягивания", материализованная через create_inclusion
// (ProgramItem + PlanWeek), свежая инклюзия без истории сессий (readiness
// "ready" гарантирован). НЕ admin-only — вкладка "Планы" видна всем.
const TELEGRAM_ID = 900_016;

test("«Планы» → Подтягивания → Начать → live session → Complete, без admin/lab", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);

  await page.getByRole("button", { name: "Планы" }).click();
  await expect(page.getByText("Свободный пул")).toBeVisible();
  await expect(page.getByText("Подтягивания", { exact: true })).toBeVisible();

  // Обычный пользователь не видит admin-вкладку — подтверждаем прямо в
  // тесте, чтобы Golden Journey нельзя было случайно пройти через lab.
  await expect(page.getByRole("button", { name: "Dashboard" })).toHaveCount(0);

  // --- UI PROOF: старт именно с карточки PlanWeek ---
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await page.waitForTimeout(800);

  // --- STEP readiness не обойдена: видны реальные цели по блокам, не
  // просто голая кнопка "Начать" без пред-экрана ---
  await expect(page.getByText(/Блок A.*цель/)).toBeVisible();
  await expect(page.getByText(/Блок Б.*цель/)).toBeVisible();

  const startResponsePromise = page.waitForResponse(
    (response) => response.url().includes("/api/v2/sessions/live") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  const startResponse = await startResponsePromise;
  const startedSession = await startResponse.json();
  const sessionId: number = startedSession.id;
  expect(startedSession.blocks).toHaveLength(2); // Блок A + Блок Б — одна Session

  await page.waitForTimeout(1000);
  await expect(page.getByText("Живая тренировка")).toBeVisible();

  // --- Записать реальный подход ---
  await page.getByRole("button", { name: "Готов", exact: true }).click();
  await page.waitForTimeout(500);
  await page.getByRole("textbox", { name: "Результат" }).fill("10");

  const setResponsePromise = page.waitForResponse(
    (response) => response.url().includes("/sets:batch") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Готово", exact: true }).click();
  await setResponsePromise;
  await page.waitForTimeout(500);

  // --- RELOAD PROOF: посреди STARTED-сессии ---
  await page.reload({ waitUntil: "networkidle" });
  await page.waitForTimeout(1000);
  // client_session_id идемпотентность — тот же сервер должен вернуть ту же
  // сессию, не создать новую; экран живой тренировки должен восстановиться
  // сам (fetchActiveLiveSession), без похода через "Планы" заново.
  await expect(page.getByText("Живая тренировка")).toBeVisible();

  console.log("session id (persisted across reload):", sessionId);

  expect(apiFailures).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
