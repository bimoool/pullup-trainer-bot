import { expect, test, type Page } from "@playwright/test";

import { noWakeLock } from "../fixtures/builderFlow";
import { buildInitData, getTestBotToken } from "../fixtures/initData";
import { openAppAs } from "../fixtures/setup";

/**
 * issue #306 — Live Engine v2 (docs/domain/LIVE_ENGINE_V2.md, ACCEPTANCE J5). Сид: scripts/e2e_seed.py
 * live_engine (930601…930607) — Builder-тренировки с короткими таймингами версии v2, поэтому автопереходы
 * проверяются реальным временем сервера: никаких кликов «Готов» / «Пропустить отдых» / «Начать».
 * Вьюпорт — iPhone-размер (390×844, touch); отдельная проверка 320 px. Физический iPhone здесь не участвует.
 */
test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 3 });
test.setTimeout(120_000);

const API_ACTIVE = "/api/v2/sessions/live/active";

async function startPlanned(page: Page, title: string) {
  const tabbar = page.locator(".bottom-tabbar");
  await expect(tabbar.or(page.getByRole("button", { name: /Назад/ }).first()).first()).toBeVisible();
  await page.getByRole("button", { name: "Планы" }).click();
  const group = page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${title}`) });
  await group.getByRole("button", { name: /^Начать: / }).first().click();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await expect(page.getByText("Живая тренировка")).toBeVisible();
}

const phase = (page: Page) => page.getByTestId("engine-phase");

/** Ни одной обязательной кнопки перехода движка v1. */
async function expectNoManualTransitions(page: Page) {
  for (const name of ["Готов", "Пропустить отдых", "Начать"]) {
    await expect(page.getByRole("button", { name, exact: true })).toHaveCount(0);
  }
}

async function serverRemainingSeconds(page: Page, telegramId: number): Promise<number | null> {
  const initData = buildInitData({ id: telegramId, firstName: "E2E" }, getTestBotToken());
  const response = await page.request.get(API_ACTIVE, { headers: { "X-Telegram-Init-Data": initData } });
  const body = await response.json();
  const engine = body.session?.engine;
  if (!engine) {
    return null;
  }
  const state = engine.state;
  const remaining = state.paused_at !== null ? state.paused_remaining_ms : state.phase_deadline_at - engine.server_time_ms;
  return remaining / 1000;
}

function parseTimer(text: string): number {
  const [m, s] = text.trim().split(":").map(Number);
  return m * 60 + s;
}

test("1. PREP → WORK по дедлайну, без тапа", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, 930_601);
  await startPlanned(page, "Движок: подходы");
  await expect(phase(page)).toHaveText("Приготовься");
  await expectNoManualTransitions(page);
  await expect(page.getByTestId("engine-skip")).toBeVisible(); // необязательное «Начать сейчас»
  await expect(phase(page)).toHaveText("Пошёл", { timeout: 8_000 }); // сам
  await expect(page.getByTestId("engine-target")).toContainText("Подход 1/2");
  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});

test("2. REST → следующий WORK по дедлайну; таймер = сервер ±1 с", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, 930_602);
  await startPlanned(page, "Движок: подходы");
  await expect(phase(page)).toHaveText("Пошёл", { timeout: 8_000 });
  await page.getByLabel("Результат подхода").fill("5");
  await page.getByTestId("engine-submit").click();
  await expect(phase(page)).toHaveText("Отдых");
  await expectNoManualTransitions(page);
  const shown = parseTimer(await page.getByTestId("engine-timer").innerText());
  const server = await serverRemainingSeconds(page, 930_602);
  expect(server).not.toBeNull();
  expect(Math.abs(shown - (server as number))).toBeLessThanOrEqual(1.5); // E: ±1 с (+ округление вверх)
  await expect(phase(page)).toHaveText("Пошёл", { timeout: 10_000 });
  await expect(page.getByTestId("engine-target")).toContainText("Подход 2/2");
  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});

test("3. Отдых блока → следующий блок сам; подход на время засчитывается сам; итог", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, 930_603);
  await startPlanned(page, "Движок: блоки");
  await expect(phase(page)).toHaveText("Пошёл"); // prep 0
  await page.getByLabel("Результат подхода").fill("3");
  await page.getByTestId("engine-submit").click();
  await expect(phase(page)).toHaveText("Отдых");
  await expect(page.getByTestId("engine-next-block")).toContainText("Планка");
  await expectNoManualTransitions(page);
  await expect(page.getByText("Планка").first()).toBeVisible();
  await expect(phase(page)).toHaveText("Приготовься", { timeout: 10_000 }); // блок B начался сам
  await expect(phase(page)).toHaveText("Пошёл", { timeout: 6_000 });
  await expect(page.getByTestId("engine-complete")).toBeVisible({ timeout: 10_000 }); // 5 с планки — сами
  await page.getByTestId("engine-save").click();
  await expect(page.getByText("Тренировка завершена").first()).toBeVisible();
  await expect(page.getByText("Подход 1: 3 повт.")).toBeVisible();
  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});

test("4. Фон/перезагрузка поперёк дедлайна: на возврате фаза уже переключена", async ({ page, context }) => {
  await openAppAs(page, 930_604);
  await startPlanned(page, "Движок: подходы");
  await expect(phase(page)).toHaveText("Пошёл", { timeout: 8_000 });
  await page.getByLabel("Результат подхода").fill("5");
  await page.getByTestId("engine-submit").click();
  await expect(phase(page)).toHaveText("Отдых");
  await page.close(); // приложение закрыто/в фоне
  await new Promise((resolve) => setTimeout(resolve, 8_000)); // отдых 6 с истёк, пока экрана не было
  const back = await context.newPage();
  const { apiFailures } = await openAppAs(back, 930_604);
  await expect(back.getByTestId("engine-phase")).toHaveText("Пошёл", { timeout: 10_000 });
  await expect(back.getByTestId("engine-target")).toContainText("Подход 2/2");
  await expect(back.getByText("Отдых", { exact: true })).toHaveCount(0);
  expect(apiFailures).toEqual([]);
});

test("5. Пауза на сервере: переживает перезагрузку и второе устройство; «Продолжить» — тот же остаток", async ({ page, browser }) => {
  await openAppAs(page, 930_605);
  await startPlanned(page, "Движок: пауза");
  await expect(phase(page)).toHaveText("Пошёл", { timeout: 8_000 });
  await page.getByLabel("Результат подхода").fill("5");
  await page.getByTestId("engine-submit").click();
  await expect(phase(page)).toHaveText("Отдых");
  await page.getByTestId("pause-toggle").click();
  await expect(phase(page)).toHaveText("Отдых · пауза");
  await expect(page.getByTestId("engine-pending")).toHaveCount(0, { timeout: 5_000 }); // дошло до сервера
  const frozen = parseTimer(await page.getByTestId("engine-timer").innerText());
  await new Promise((resolve) => setTimeout(resolve, 3_000));
  expect(parseTimer(await page.getByTestId("engine-timer").innerText())).toBe(frozen); // стоит

  await page.reload();
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых · пауза", { timeout: 10_000 }); // F
  expect(parseTimer(await page.getByTestId("engine-timer").innerText())).toBe(frozen);

  const other = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const device = await other.newPage();
  await openAppAs(device, 930_605);
  await expect(device.getByTestId("engine-phase")).toHaveText("Отдых · пауза", { timeout: 10_000 }); // G
  await other.close();

  await page.getByTestId("pause-toggle").click(); // H
  await expect(phase(page)).toHaveText("Отдых");
  await new Promise((resolve) => setTimeout(resolve, 1_500));
  const afterResume = await serverRemainingSeconds(page, 930_605);
  expect(afterResume).not.toBeNull();
  expect(Math.abs((afterResume as number) - (frozen - 1.5))).toBeLessThanOrEqual(1.5);
});

test("6. Интервал на том же движке: пауза/перезагрузка/продолжение, завершение само", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, 930_606);
  await startPlanned(page, "Движок: интервал");
  await expect(phase(page)).toHaveText("Приготовься");
  await expect(phase(page)).toHaveText("Пошёл", { timeout: 6_000 });
  await expect(page.getByTestId("engine-target")).toContainText("Раунд 1/2");
  await page.getByTestId("pause-toggle").click();
  await expect(phase(page)).toHaveText("Пошёл · пауза");
  await page.reload();
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл · пауза", { timeout: 10_000 });
  await page.getByTestId("pause-toggle").click();
  await expect(phase(page)).toHaveText("Отдых", { timeout: 8_000 });
  await expect(page.getByTestId("engine-target")).toContainText("Раунд 1/2");
  await expect(page.getByTestId("engine-complete")).toBeVisible({ timeout: 25_000 });
  await page.getByTestId("engine-save").click();
  await expect(page.getByText("Тренировка завершена").first()).toBeVisible();
  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});

/** #306 B1: сохранённые очереди движка v2 в IndexedDB (idb-keyval: keyval-store/keyval), по сессиям. */
async function storedEngineQueues(page: Page): Promise<number> {
  return page.evaluate(() => new Promise<number>((resolve, reject) => {
    const open = indexedDB.open("keyval-store");
    open.onerror = () => reject(open.error);
    open.onsuccess = () => {
      const db = open.result;
      if (!db.objectStoreNames.contains("keyval")) {
        resolve(0);
        return;
      }
      const request = db.transaction("keyval").objectStore("keyval").getAllKeys();
      request.onsuccess = () => resolve(request.result.filter((key) => String(key).startsWith("pullup:v2:live-engine-queue")).length);
      request.onerror = () => reject(request.error);
    };
  }));
}

async function serverEngineState(page: Page, telegramId: number) {
  const initData = buildInitData({ id: telegramId, firstName: "E2E" }, getTestBotToken());
  const response = await page.request.get(API_ACTIVE, { headers: { "X-Telegram-Init-Data": initData } });
  return (await response.json()).session?.engine?.state ?? null;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

test("8. #306 B1: «Стоп» подхода на время офлайн, приложение перезапущено после дедлайна — записано измеренное, не цель", async ({ page, context }) => {
  await openAppAs(page, 930_608);
  await startPlanned(page, "Движок: стоп");
  await expect(phase(page)).toHaveText("Пошёл", { timeout: 8_000 }); // планка 15 с
  await context.setOffline(true);
  await sleep(3_000);
  await page.getByTestId("engine-stop").click(); // Стоп на ~3 с — событие только в очереди устройства
  await expect(phase(page)).not.toHaveText("Пошёл");
  expect(await storedEngineQueues(page)).toBe(1);
  await page.close(); // WebView выгружен
  await sleep(15_000); // дедлайн подхода (15 с) прошёл, пока приложения не было
  await context.setOffline(false);
  const back = await context.newPage();
  const { apiFailures } = await openAppAs(back, 930_608); // запуск: досылка очереди → затем GET /active
  await expect(back.getByTestId("engine-phase")).toHaveText(/Пошёл|Отдых/, { timeout: 10_000 });
  const state = await serverEngineState(back, 930_608);
  expect(state).not.toBeNull();
  expect(state.logs[0].block_index).toBe(0);
  expect(state.logs[0].value).toBeGreaterThanOrEqual(2);
  expect(state.logs[0].value).toBeLessThanOrEqual(7); // измеренное, а не цель 15
  expect(await storedEngineQueues(back)).toBe(0); // очередь снята после подтверждения сервером
  expect(apiFailures).toEqual([]);
});

test("9. #306 B1: пауза интервала офлайн, приложение перезапущено позже — на паузе, остаток тот же, не завершилась сама", async ({ page, context, browser }) => {
  await openAppAs(page, 930_609);
  await startPlanned(page, "Движок: интервал"); // 3 с + 2 × (5 + 4) с ≈ 21 с без паузы
  await expect(phase(page)).toHaveText("Пошёл", { timeout: 6_000 });
  await context.setOffline(true);
  await page.getByTestId("pause-toggle").click();
  await expect(phase(page)).toHaveText("Пошёл · пауза");
  const frozen = parseTimer(await page.getByTestId("engine-timer").innerText());
  expect(await storedEngineQueues(page)).toBe(1);
  await page.close();
  await sleep(25_000); // без паузы интервал уже закончился бы сам
  await context.setOffline(false);
  const back = await context.newPage();
  const { apiFailures } = await openAppAs(back, 930_609);
  await expect(back.getByTestId("engine-phase")).toHaveText("Пошёл · пауза", { timeout: 10_000 });
  expect(Math.abs(parseTimer(await back.getByTestId("engine-timer").innerText()) - frozen)).toBeLessThanOrEqual(1);
  const state = await serverEngineState(back, 930_609);
  expect(state.status).toBe("active");
  expect(state.paused_at).not.toBeNull();
  expect(Math.abs(state.paused_remaining_ms / 1000 - frozen)).toBeLessThanOrEqual(1.5);
  expect(await storedEngineQueues(back)).toBe(0);
  const other = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const device = await other.newPage(); // второе устройство видит ту же паузу
  await openAppAs(device, 930_609);
  await expect(device.getByTestId("engine-phase")).toHaveText("Пошёл · пауза", { timeout: 10_000 });
  await other.close();
  expect(apiFailures).toEqual([]);
});

test.describe("320 px", () => {
  test.use({ viewport: { width: 320, height: 640 } });

  test("7. Экран движка без горизонтальной прокрутки на 320 px", async ({ page }) => {
    await openAppAs(page, 930_607);
    await startPlanned(page, "Движок: пауза");
    await expect(phase(page)).toHaveText("Пошёл", { timeout: 8_000 });
    await page.getByLabel("Результат подхода").fill("5");
    for (const state of ["work", "rest"]) {
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, state).toBeLessThanOrEqual(0);
      if (state === "work") {
        await page.getByTestId("engine-submit").click();
        await expect(phase(page)).toHaveText("Отдых");
      }
    }
    await expect(page.getByTestId("pause-toggle")).toBeInViewport();
    await expect(page.getByTestId("engine-skip")).toBeInViewport();
  });
});
