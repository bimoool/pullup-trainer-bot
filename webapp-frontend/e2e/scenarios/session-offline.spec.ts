import { expect, test } from "@playwright/test";

import { noWakeLock, playSetsV2 } from "../fixtures/builderFlow";
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
  await expect(page.getByTestId("engine-phase")).toHaveText("Приготовься");

  // Сеть отключается ПОСЛЕ старта сессии (POST /sessions/live уже прошёл онлайн).
  await context.setOffline(true);

  // issue #306 (Live Engine v2): офлайн экран рисует проекцию той же функцией переходов, что сервер;
  // действия — события в очереди (IndexedDB). Ожидание сокращается «Начать сейчас» (skip_wait).
  // Блок A — 3 подхода, отдых блока, блок Б — 1 подход: всё офлайн.
  await playSetsV2(page, ["10", "10", "10", "3"]);

  await expect(page.getByTestId("engine-complete")).toBeVisible();
  await expect(page.getByText(/Нет сети/)).toBeVisible();

  // Враждебный тайминг НАМЕРЕННО: реконнект сам запускает досылку очереди (событие "online"),
  // а «Сохранить» тапается СРАЗУ. Досылка single-flight: события уходят одним запросом по порядку,
  // повтор — no-op по client_event_id; завершение — ровно один POST /complete.
  const liveResponses: { path: string; status: number }[] = [];
  page.on("response", (response) => {
    const url = decodeURIComponent(response.url());
    if (url.includes("/api/v2/sessions/live/")) {
      liveResponses.push({ path: new URL(url).pathname, status: response.status() });
    }
  });
  await context.setOffline(false);
  await page.getByTestId("engine-save").click();

  await expect(page.getByText("Тренировка завершена").first()).toBeVisible();
  await expect(page.getByTestId("engine-phase")).toHaveCount(0); // Summary, не экран движка
  expect(liveResponses.filter((r) => r.status >= 500)).toEqual([]);
  expect(liveResponses.some((r) => r.path.endsWith("/events") && r.status === 200)).toBe(true);
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
