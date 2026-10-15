import { expect, test } from "@playwright/test";

import { openTab } from "../fixtures/parity";
import { openAppAs } from "../fixtures/setup";
import { confirmQuestions, mockTelegramWebConfirm } from "../fixtures/telegramMock";

/**
 * Аудит staging 6475bc0: подтверждения через window.confirm в Telegram Web (iframe) не показываются и сразу дают
 * «нет» — удаление в журнале/тестах/замерах молча не срабатывало. Все пользовательские подтверждения идут через
 * confirmAction (нативный WebApp.showConfirm). Здесь window.confirm заблокирован как в Telegram Web: «Нет» сохраняет
 * данные, «Да» выполняет действие. Сиды: journal_dedupe 999621, body_metrics 999221, tests_hub 996021. 320 px.
 */
test.use({ viewport: { width: 320, height: 640 }, isMobile: true, hasTouch: true });
test.setTimeout(90_000);

test("журнал: удаление тренировки — «Нет» сохраняет, «Да» удаляет", async ({ page }) => {
  const { apiFailures } = await openAppAs(page, 999_621);
  await mockTelegramWebConfirm(page, [false, true]);
  await openTab(page, "Журнал");
  const legacyCards = page.locator(".history-card:not(.history-card-clickable)");
  const card13 = legacyCards.filter({ hasText: "максимум 13" });
  await expect(legacyCards).toHaveCount(4);

  await card13.getByRole("button", { name: /Удалить/ }).click();
  await expect.poll(() => confirmQuestions(page)).toHaveLength(1);
  await page.waitForTimeout(300);
  await expect(legacyCards).toHaveCount(4);

  await card13.getByRole("button", { name: /Удалить/ }).click();
  await expect(card13).toHaveCount(0);
  await expect(legacyCards).toHaveCount(3);
  expect((await confirmQuestions(page))[0]).toContain("Удалить эту тренировку");
  expect(apiFailures).toEqual([]);
});

test("замеры: удаление — «Нет» сохраняет, «Да» удаляет", async ({ page }) => {
  const { apiFailures } = await openAppAs(page, 999_221);
  await mockTelegramWebConfirm(page, [false, true]);
  await openTab(page, "Профиль");
  await page.getByTestId("profile-weight").click();
  const rows = page.getByTestId("body-metrics-row");
  await expect(rows).toHaveCount(3);

  await page.getByTestId("body-metrics-delete").first().click();
  await expect.poll(() => confirmQuestions(page)).toHaveLength(1);
  await page.waitForTimeout(300);
  await expect(rows).toHaveCount(3);

  await page.getByTestId("body-metrics-delete").first().click();
  await expect(rows).toHaveCount(2);
  expect((await confirmQuestions(page))[1]).toContain("Удалить замер");
  expect(apiFailures).toEqual([]);
});

test("тесты: удаление результата — «Нет» сохраняет, «Да» удаляет", async ({ page }) => {
  const { apiFailures } = await openAppAs(page, 996_021);
  await mockTelegramWebConfirm(page, [false, true]);
  await page.getByTestId("home-tests-row").click();
  await page.getByTestId("test-card").filter({ hasText: "Максимум подтягиваний" }).click();
  const rows = page.getByTestId("test-history-row");
  await expect(rows.first()).toBeVisible();
  const before = await rows.count();
  expect(before).toBeGreaterThan(0);

  await rows.first().getByRole("button", { name: /^Удалить/ }).click();
  await expect.poll(() => confirmQuestions(page)).toHaveLength(1);
  await page.waitForTimeout(300);
  await expect(rows).toHaveCount(before);

  await rows.first().getByRole("button", { name: /^Удалить/ }).click();
  await expect(rows).toHaveCount(before - 1);
  expect((await confirmQuestions(page))[1]).toContain("Удалить результат");
  expect(apiFailures).toEqual([]);
});
