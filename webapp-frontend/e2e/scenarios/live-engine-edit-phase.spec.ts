import { expect, test, type Page } from "@playwright/test";

import { buildInitData, getTestBotToken } from "../fixtures/initData";
import { openAppAs } from "../fixtures/setup";

/**
 * Аудит staging 6475bc0 (Telegram Web, 375 px):
 *  H2 — в отдыхе «Изменить» → ввести 4 → не нажимать «Сохранить» → отдых кончился: редактор закрывался, 4 молча
 *       пропадало. Теперь черновик сохраняется (correct_previous) и об этом есть сообщение.
 *  H3 — пока открыт редактор, нижняя панель скрыта (узкий экран), и не было ни «Паузы», ни «Отмены». Теперь обе
 *       кнопки в самом редакторе: пауза останавливает отдых, «Отмена» закрывает правку без сохранения.
 * Сид: scripts/e2e_seed.py live_engine (у «Движок: подходы» отдых после 1-го подхода 6 с). По пользователю на тест и retry.
 */
test.use({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true });
test.setTimeout(90_000);

type Log = { set_index: number; is_extra: boolean; value: number | null };

async function serverFirstSet(page: Page, telegramId: number): Promise<number | null> {
  const initData = buildInitData({ id: telegramId, firstName: "E2E" }, getTestBotToken());
  const response = await page.request.get("/api/v2/sessions/live/active", { headers: { "X-Telegram-Init-Data": initData } });
  const session = (await response.json()).session as { engine?: { state: { logs: Log[] } } } | null;
  return session?.engine?.state.logs.find((log) => log.set_index === 0 && !log.is_extra)?.value ?? null;
}

async function startAndLogFirstSet(page: Page, telegramId: number) {
  const opened = await openAppAs(page, telegramId);
  await page.getByRole("button", { name: "Планы" }).click();
  const group = page.locator(".plan-week-day-group").filter({ hasText: /^Движок: подходы/ });
  await group.getByRole("button", { name: /^Начать: / }).first().click();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл", { timeout: 10_000 });
  await page.getByLabel("Результат подхода").fill("6");
  await page.getByTestId("engine-submit").click();
  await expect(page.locator(".live-screen")).toHaveAttribute("data-engine-phase", "REST", { timeout: 10_000 });
  await expect.poll(() => serverFirstSet(page, telegramId), { timeout: 10_000 }).toBe(6);
  return opened;
}

test("H2: отдых кончился при открытой правке — введённое значение сохраняется, а не пропадает", async ({ page }, testInfo) => {
  const telegramId = 930_623 + testInfo.retry;
  const { apiFailures } = await startAndLogFirstSet(page, telegramId);

  await page.getByTestId("engine-edit-last").click();
  await page.getByLabel("Исправить подход").fill("4");
  // «Сохранить подход» не нажимаем — ждём конца отдыха (6 с).
  await expect(page.locator(".live-screen")).toHaveAttribute("data-engine-phase", "WORK", { timeout: 15_000 });
  await expect(page.getByLabel("Исправить подход")).toHaveCount(0);
  await expect(page.getByTestId("app-toast")).toHaveText("Подход 1 исправлен: 4");
  await expect.poll(() => serverFirstSet(page, telegramId), { timeout: 10_000 }).toBe(4);
  expect(apiFailures).toEqual([]);
});

test("H3: в правке подхода есть «Пауза» (останавливает отдых) и «Отмена» (без сохранения)", async ({ page }, testInfo) => {
  const telegramId = 930_625 + testInfo.retry;
  const { apiFailures } = await startAndLogFirstSet(page, telegramId);

  await page.getByTestId("engine-edit-last").click();
  await page.getByLabel("Исправить подход").fill("4");
  const pause = page.getByTestId("engine-edit-pause");
  await expect(pause).toHaveText("Пауза");
  await pause.click();
  await expect(page.locator(".live-screen")).toHaveAttribute("data-paused", "true");
  await expect(pause).toHaveText("Продолжить");
  // Отдых (6 с) прошёл бы — на паузе фаза не меняется, правка открыта и значение на месте.
  await page.waitForTimeout(8_000);
  await expect(page.locator(".live-screen")).toHaveAttribute("data-engine-phase", "REST");
  await expect(page.getByLabel("Исправить подход")).toHaveValue("4");

  await page.getByTestId("engine-edit-cancel").click();
  await expect(page.getByLabel("Исправить подход")).toHaveCount(0);
  await expect(page.getByTestId("log-panel-summary")).toContainText("6");
  await expect(page.getByTestId("pause-toggle")).toHaveText("Продолжить"); // панель вернулась, пауза держится
  expect(await serverFirstSet(page, telegramId)).toBe(6); // «Отмена» ничего не отправила

  await page.getByTestId("pause-toggle").click();
  await expect(page.locator(".live-screen")).toHaveAttribute("data-engine-phase", "WORK", { timeout: 15_000 });
  expect(await serverFirstSet(page, telegramId)).toBe(6); // и после конца отдыха отменённое не сохранилось
  expect(apiFailures).toEqual([]);
});
