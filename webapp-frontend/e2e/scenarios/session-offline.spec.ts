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
    await page.getByLabel("Повторений").fill("10");
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
  await page.getByLabel("Повторений").fill("3");
  await page.getByRole("button", { name: "Готово" }).click();

  await expect(page.getByText("Все подходы плана выполнены")).toBeVisible();
  await expect(page.getByText(/Нет сети/)).toBeVisible();

  // Враждебный тайминг НАМЕРЕННО (fix/concurrent-set-batch): реконнект сам
  // запускает синхронизацию накопленного (событие "online" -> POST
  // /sets:batch), и "Завершить" тапается СРАЗУ, не дожидаясь её. Раньше это
  // слало второй такой же батч параллельно и ловило 500
  // (uq_set_logs_session_set_index); теперь сервер к дублю устойчив, а клиент
  // досылает одним флашем за раз. Не добавлять сюда ожидание синхронизации.
  const liveResponses: { path: string; status: number }[] = [];
  page.on("response", (response) => {
    const url = decodeURIComponent(response.url());
    if (url.includes("/api/v2/sessions/live/")) {
      liveResponses.push({ path: new URL(url).pathname, status: response.status() });
    }
  });
  await context.setOffline(false);
  await page.getByRole("button", { name: "Завершить" }).click();
  await page.getByRole("button", { name: "Сохранить и завершить", exact: true }).click();

  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  expect(liveResponses.filter((r) => r.status >= 500)).toEqual([]);
  expect(liveResponses.some((r) => r.path.endsWith("/sets:batch") && r.status === 200)).toBe(true);
  expect(liveResponses.filter((r) => r.path.endsWith("/complete"))).toEqual([
    expect.objectContaining({ status: 200 }),
  ]);
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
