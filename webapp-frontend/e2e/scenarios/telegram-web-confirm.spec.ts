import { expect, test, type Page } from "@playwright/test";

import { openTab } from "../fixtures/parity";
import { openAppAs } from "../fixtures/setup";

/**
 * Аудит staging 6475bc0 (H1): в Telegram Web Mini App живёт в iframe, где window.confirm не показывается и сразу
 * возвращает false, — «Удалить» в Журнале и в Тестах молча ничего не делало. Подтверждение идёт через нативный
 * WebApp.showConfirm (confirmAction); после удаления — сообщение «… удалена/удалён».
 * Сиды: journal_edit (Builder-запись «Моя силовая» удаляемая), peer_empty (без результатов: тест сам записывает 999,
 * как в аудите, в протокол, которого не касается peer-insights.spec.ts, и удаляет его).
 * Мутирует данные — по пользователю на тест и retry.
 */
test.use({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true });
test.setTimeout(90_000);

/** Как в Telegram Web: window.confirm заблокирован (false без диалога), нативное подтверждение отвечает `answer`. */
async function telegramWebConfirm(page: Page, answer: boolean) {
  await page.evaluate((ok) => {
    const w = window as unknown as {
      confirm: () => boolean; __asked: string[];
      Telegram: { WebApp: { showConfirm?: (message: string, callback: (confirmed: boolean) => void) => void } };
    };
    w.__asked = [];
    w.confirm = () => false;
    w.Telegram.WebApp.showConfirm = (message, callback) => {
      w.__asked.push(message);
      setTimeout(() => callback(ok), 0);
    };
  }, answer);
}

const asked = (page: Page) => page.evaluate(() => (window as unknown as { __asked: string[] }).__asked);

test("Журнал: «Удалить» в Telegram Web спрашивает нативно; «Нет» — запись на месте, «Да» — удалена с сообщением", async ({ page }, testInfo) => {
  const { apiFailures } = await openAppAs(page, 998_191 + testInfo.retry);
  await openTab(page, "Журнал");
  const card = page.locator(".history-card-clickable").filter({ hasText: "Моя силовая" });
  await expect(card).toHaveCount(1);

  await telegramWebConfirm(page, false);
  await card.click();
  await page.getByTestId("journal-sheet-delete").click();
  await expect.poll(() => asked(page)).toEqual(["Удалить эту тренировку? Отменить это будет нельзя."]);
  await page.waitForTimeout(500);
  await expect(page.getByTestId("app-toast")).toHaveCount(0);
  await page.getByTestId("journal-sheet-cancel").click();
  await expect(card).toHaveCount(1);

  await telegramWebConfirm(page, true);
  await card.click();
  const deleted = page.waitForResponse((r) => r.request().method() === "DELETE" && r.url().includes("/api/v2/sessions/"));
  await page.getByTestId("journal-sheet-delete").click();
  expect((await deleted).ok()).toBe(true);
  await expect(page.getByTestId("app-toast")).toHaveText("Тренировка удалена");
  await expect(card).toHaveCount(0);
  expect(apiFailures).toEqual([]);
});

test("Тест: «Удалить результат» в Telegram Web спрашивает нативно и удаляет с сообщением", async ({ page }, testInfo) => {
  const { apiFailures } = await openAppAs(page, 998_193 + testInfo.retry);
  await openTab(page, "Профиль");
  // Не «Максимум подтягиваний» / «Подтягивания с весом»: их когорты проверяет peer-insights.spec.ts.
  await page.getByTestId("test-card").filter({ hasNotText: /Максимум подтягиваний|Подтягивания с весом/ }).first().click();
  await expect(page.getByTestId("test-detail")).toBeVisible();
  const rows = page.getByTestId("test-history-row");
  await expect(page.getByTestId("test-history-empty")).toBeVisible();
  await page.locator("#test-value").fill("999");
  await page.getByRole("button", { name: "Записать результат" }).click();
  await expect(rows).toHaveCount(1);
  const remove = rows.first().getByRole("button", { name: /^Удалить результат/ });

  await telegramWebConfirm(page, false);
  await remove.click();
  await expect.poll(() => asked(page)).toHaveLength(1);
  expect((await asked(page))[0]).toMatch(/^Удалить результат 999\b.* от /);
  await page.waitForTimeout(500);
  await expect(rows).toHaveCount(1);

  await telegramWebConfirm(page, true);
  await remove.click();
  await expect(page.getByTestId("app-toast")).toHaveText("Результат удалён");
  await expect(rows).toHaveCount(0);
  await expect(page.getByTestId("test-history-empty")).toBeVisible();
  expect(apiFailures).toEqual([]);
});
