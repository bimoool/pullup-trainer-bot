import { expect, test, type Page } from "@playwright/test";

import { heldIdbWrites, installIdbWriteGate, releaseIdbWrites, setIdbWriteMode } from "../fixtures/idbGate";
import { buildInitData, getTestBotToken } from "../fixtures/initData";
import { openAppAs } from "../fixtures/setup";

/**
 * MVP: сохранность результата подхода (Live Engine v2). Раньше enqueue() обновлял экран (setQueue → «Отдых»,
 * «Подход 1: N») ДО того, как очередь записана в IndexedDB: закрыли/перезагрузили приложение в этом окне —
 * подтверждённый интерфейсом результат пропадал (live-engine-v2 #4/#12 падали на гонке «закрыто через ~40 мс»).
 * Теперь: экран подтверждает действие только после записи на устройство; пока запись идёт — это видно; при
 * ошибке записи введённое остаётся и есть «Повторить» (то же событие: client_event_id и время нажатия).
 * Запись IndexedDB управляется тестом (fixtures/idbGate) — без фиксированных пауз.
 * Сид: live_engine 930627–930629 («Движок: подходы»: 2 × 5, отдых 6 с).
 */
test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
test.setTimeout(90_000);

const API_ACTIVE = "/api/v2/sessions/live/active";
type Log = { block_index: number; set_index: number; value: number | null; is_extra?: boolean };

async function startSets(page: Page) {
  await page.getByRole("button", { name: "Планы" }).click();
  const group = page.locator(".plan-week-day-group").filter({ hasText: /^Движок: подходы/ });
  await group.getByRole("button", { name: /^Начать: / }).first().click();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл", { timeout: 10_000 });
}

async function serverLogs(page: Page, telegramId: number): Promise<Log[]> {
  const initData = buildInitData({ id: telegramId, firstName: "E2E" }, getTestBotToken());
  const response = await page.request.get(API_ACTIVE, { headers: { "X-Telegram-Init-Data": initData } });
  return ((await response.json()).session?.engine?.state?.logs ?? []) as Log[];
}

const firstSet = (logs: Log[]) => logs.filter((log) => log.block_index === 0 && log.set_index === 0 && !log.is_extra);

test("запись ещё идёт: «Готово» не подтверждает подход, это видно; перезагрузка не показывает фантом", async ({ page }) => {
  const telegramId = 930_627;
  await installIdbWriteGate(page);
  await openAppAs(page, telegramId);
  await startSets(page);
  const posts: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && /\/sessions\/live\/\d+\/events$/.test(request.url())) {
      posts.push(request.postData() ?? "");
    }
  });

  await setIdbWriteMode(page, "hold");
  await page.getByLabel("Результат подхода").fill("4");
  await page.getByTestId("engine-submit").click();
  await expect.poll(() => heldIdbWrites(page)).toBe(1);
  // Пока запись на устройство не завершена: явно «Сохраняю…», подход не подтверждён, введённое на месте.
  await expect(page.getByTestId("engine-saving")).toBeVisible();
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл");
  await expect(page.getByTestId("engine-target")).toContainText("Подход 1/2");
  await expect(page.getByLabel("Результат подхода")).toHaveValue("4");
  await expect(page.getByTestId("engine-submit")).toBeDisabled();
  await expect(page.getByText("Подход 1: 4 повт.")).toHaveCount(0);
  expect(posts).toEqual([]);

  await page.reload();  // закрыли до коммита: ничего не подтверждалось — и ничего не «появилось»
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл", { timeout: 15_000 });
  await expect(page.getByTestId("engine-target")).toContainText("Подход 1/2");
  expect(firstSet(await serverLogs(page, telegramId))).toEqual([]);
});

test("подтверждённый подход переживает закрытие сразу после подтверждения, даже без сети к серверу", async ({ page, context }) => {
  const telegramId = 930_628;
  await installIdbWriteGate(page);
  await openAppAs(page, telegramId);
  await startSets(page);
  await page.route("**/api/v2/sessions/live/*/events", (route) => route.abort("failed"));  // досылка — только из устройства

  await setIdbWriteMode(page, "hold");
  await page.getByLabel("Результат подхода").fill("4");
  await page.getByTestId("engine-submit").click();
  await expect(page.getByTestId("engine-saving")).toBeVisible();
  expect(await releaseIdbWrites(page)).toBe(1);
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых");
  await expect(page.getByText("Подход 1: 4 повт.")).toBeVisible();
  await expect(page.getByTestId("engine-saving")).toHaveCount(0);
  await page.close();  // сразу после подтверждения

  const back = await context.newPage();
  const { apiFailures } = await openAppAs(back, telegramId);
  await expect.poll(async () => firstSet(await serverLogs(back, telegramId)).map((log) => log.value), { timeout: 15_000 }).toEqual([4]);
  await expect(back.getByTestId("engine-phase")).toHaveText(/Отдых|Пошёл/, { timeout: 10_000 });
  await expect(back.getByTestId("engine-target")).toContainText("Подход 2/2", { timeout: 15_000 });
  expect(apiFailures).toEqual([]);
});

test("ошибка записи: введённое остаётся, «Повторить» отправляет то же событие один раз", async ({ page }) => {
  const telegramId = 930_629;
  await installIdbWriteGate(page);
  await openAppAs(page, telegramId);
  await startSets(page);
  const submitted: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && /\/sessions\/live\/\d+\/events$/.test(request.url())) {
      for (const event of (request.postDataJSON()?.events ?? []) as { type: string; client_event_id: string }[]) {
        if (event.type === "submit_result") {
          submitted.push(event.client_event_id);
        }
      }
    }
  });

  await setIdbWriteMode(page, "fail");
  await page.getByLabel("Результат подхода").fill("3");
  await page.getByTestId("engine-submit").click();
  const error = page.getByTestId("engine-save-error");
  await expect(error).toBeVisible();
  await expect(error).toContainText("Введённое не потеряно");
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл");
  await expect(page.getByLabel("Результат подхода")).toHaveValue("3");
  await expect(page.getByTestId("engine-saving")).toHaveCount(0);
  expect(submitted).toEqual([]);

  await setIdbWriteMode(page, "pass");
  await error.getByRole("button", { name: "Повторить" }).click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых");
  await expect(page.getByText("Подход 1: 3 повт.")).toBeVisible();
  await expect(error).toHaveCount(0);
  await expect.poll(async () => firstSet(await serverLogs(page, telegramId)).map((log) => log.value), { timeout: 10_000 }).toEqual([3]);
  expect(new Set(submitted).size).toBe(1);
});
