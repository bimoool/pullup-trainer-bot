import { expect, test } from "@playwright/test";

import { noWakeLock } from "../fixtures/builderFlow";
import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py v2_session_ready 900010 — STEP-курс синтетической
// категории, block_a work_sets=3 (цель 10) + block_b дефолтный 1 подход
// (цель 3) — ровно 4 подхода на сессию (см. докстринг сценария в
// scripts/e2e_seed.py). Экран сессии v2 виден только ADMIN_IDS — сценарий
// требует ADMIN_IDS=900010 (или шире) у тестового сервера, см.
// webapp-frontend/e2e/README.md.
const TELEGRAM_ID = 900_010;

// Критерий готовности раздела 15 docs/plan-and-specs.md, дословно:
// "Пользователь ready начинает сессию, вносит 4 подхода при отключённой
// сети (Playwright context.setOffline), включает сеть, завершает — на
// сервере 4 подхода, итог показывает новую цель".
test("live-сессия (v2): 4 подхода офлайн, синхронизация и завершение после подключения сети", async ({
  page,
  context,
}) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);
  page.on("dialog", (dialog) => void dialog.accept());

  await page.getByRole("button", { name: "Dashboard" }).click();
  await page.getByRole("button", { name: "Начать тренировку (v2)" }).click();
  await expect(page.getByText("E2E Live Session")).toBeVisible();

  await page.getByRole("button", { name: "Начать" }).click();
  await expect(page.getByRole("heading", { name: "Приготовься", exact: true })).toBeVisible();

  // Сеть отключается ПОСЛЕ старта сессии (POST /sessions/live уже прошёл
  // онлайн) — та же последовательность, что в тексте критерия готовности:
  // "начинает сессию, вносит подходы при отключённой сети", не "начинает
  // сессию при отключённой сети" (старт живой сессии офлайн — отдельный,
  // не реализованный в этой волне сценарий, см. докстринг SessionPreScreen.tsx
  // про то, что plan_item_ids резолвятся online-запросом /api/v2/plan).
  await context.setOffline(true);

  // Блок A — 3 подхода (get_ready -> go -> log -> rest -> get_ready -> ...).
  for (let i = 0; i < 3; i += 1) {
    await page.getByRole("button", { name: "Готов" }).click();
    await expect(page.getByRole("heading", { name: "Пошёл", exact: true })).toBeVisible();
    await page.getByLabel("Результат").fill("10");
    await page.getByRole("button", { name: "Готово" }).click();
    if (i < 2) {
      await expect(page.getByRole("heading", { name: "Отдых", exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Пропустить отдых" }).click();
    }
  }

  // Последний подход блока A ведёт СРАЗУ в get_ready блока Б (без rest) —
  // см. app.domain.live_session.next_phase: "последний подход НЕпоследнего
  // блока -> get_ready первого подхода следующего блока".
  await expect(page.getByRole("heading", { name: "Приготовься", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Готов" }).click();
  await expect(page.getByRole("heading", { name: "Пошёл", exact: true })).toBeVisible();
  await page.getByLabel("Результат").fill("3");
  await page.getByRole("button", { name: "Готово" }).click();

  await expect(page.getByText("Все подходы плана выполнены")).toBeVisible();
  await expect(page.getByText(/Нет сети/)).toBeVisible();

  // Реконнект сам запускает синхронизацию накопленных подходов (событие
  // "online" -> POST /sets:batch) — ждём её завершения и только потом
  // завершаем. Одновременный тап "Завершить" в окне реконнекта шлёт второй
  // такой же батч параллельно и ловит 500 (uq_set_logs_session_set_index) —
  // отдельный продуктовый баг, вынесен из этой стабилизации.
  const syncResponse = page.waitForResponse((r) => r.url().includes("/sets%3Abatch") || r.url().includes("/sets:batch"));
  await context.setOffline(false);
  expect((await syncResponse).status()).toBe(200);
  await expect(page.getByText(/Нет сети/)).toHaveCount(0);
  await page.getByRole("button", { name: "Завершить" }).click();

  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  // 3 подхода блока A + 1 подход блока Б = 4/4 показаны выполненными.
  await expect(page.getByText(/— 3\/3/)).toBeVisible();
  await expect(page.getByText(/— 1\/1/)).toBeVisible();
  // work_sets_a=3 в конфиге сценария — StepProgressionStrategy на "держал
  // цель" даёт новую цель блока A (см. app/domain/progression.py) — здесь
  // важен сам факт, что новая цель показана, не конкретное число.
  await expect(page.getByText("Новая цель", { exact: true })).toBeVisible();
  await expect(page.getByText(/^\d+ → \d+$/)).toHaveCount(2); // по строке на блок (A и Б)

  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});
