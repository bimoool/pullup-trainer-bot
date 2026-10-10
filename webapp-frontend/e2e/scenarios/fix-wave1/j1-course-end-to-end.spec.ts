import { expect, test, type Page } from "@playwright/test";

import { noWakeLock, playSetsV2, finishV2 } from "../../fixtures/builderFlow";
import { openAppAs } from "../../fixtures/setup";

/**
 * Fix Wave 1 re-audit J1 (#295): fresh → program → plan → workout → Live → finish → Журнал → Аналитика,
 * reload after every mutation boundary.
 *
 * Runs against a DB built only by `alembic upgrade head` (no seed scripts, no scripts/e2e_seed.py): the course
 * «Подтягивания» comes from the system-content migration (#296). The user is created by UI onboarding only.
 *
 *   cd webapp-frontend/e2e && E2E_BASE_URL=http://127.0.0.1:<port> BOT_TOKEN=<server token> \
 *     npx playwright test scenarios/fix-wave1/j1-course-end-to-end.spec.ts --project=chromium
 */

const TG = 7_900_000 + Math.floor(Math.random() * 90_000);

async function onboard(page: Page) {
  await page.getByLabel("Число подтягиваний").fill("8");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByRole("button", { name: "Да" }).click();
  await page.getByRole("button", { name: "Продолжить" }).click();
  await page.getByLabel("Вес, кг").fill("78");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Рост, см").fill("180");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Пол").selectOption({ label: "Мужской" });
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Дата рождения").fill("1992-04-15");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Часовой пояс").selectOption({ label: "Москва (UTC+3)" });
  await page.getByRole("button", { name: "Готово" }).click();
  await expect(page.getByText("Что потренируем сегодня?")).toBeVisible();
}

test.setTimeout(150_000);
test.use({ actionTimeout: 10_000 });

test("J1: новый пользователь проходит курс «Подтягивания» от каталога до Журнала и Аналитики", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TG);
  await onboard(page);

  // Каталог из миграции: курс виден новому пользователю.
  await page.getByRole("button", { name: /^Подтягивания/ }).first().click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await expect(page.getByRole("button", { name: "В плане" })).toBeVisible();

  // Планы: текущая неделя содержит стартуемую строку курса (не «0 из 0»), и после reload тоже.
  await page.reload();
  await page.getByRole("button", { name: "Планы" }).click();
  await expect(page.getByTestId("plan-week-progress").first()).not.toHaveText(/0 из 0/);
  const start = page.getByRole("button", { name: /^Начать: Подтягивания/ }).first();
  await expect(start).toBeVisible();

  // Live: пре-экран → первый блок (3 подхода) → завершить → сохранить.
  await start.click();
  await page.getByRole("button", { name: "Начать", exact: true }).click(); // SessionPreScreen
  await expect(page.getByText("Живая тренировка")).toBeVisible();
  await playSetsV2(page, ["10", "10", "10"]); // #306: блок A, переходы по дедлайну / «Начать сейчас»
  await finishV2(page, { early: true });
  await expect(page.getByText("Тренировка завершена").first()).toBeVisible();
  await page.getByRole("button", { name: "Закрыть" }).click();

  // Журнал: сессия по плану видна и переживает reload.
  await page.reload();
  await page.getByRole("button", { name: "Журнал", exact: true }).click();
  const card = page.locator(".history-card").filter({ hasText: "Подтягивания" });
  await expect(card.first()).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Журнал", exact: true }).click();
  await expect(page.locator(".history-card").filter({ hasText: "Подтягивания" }).first()).toBeVisible();

  // Аналитика учитывает тренировку.
  await page.getByRole("button", { name: "Аналитика" }).click();
  const activity = page.locator(".analytics-activity-cards");
  await expect(activity.locator(".analytics-stat").filter({ hasText: "Тренировок за 30 дней" })).toContainText("1");

  // Планы после reload: прогресс недели учёл выполненную строку.
  await page.reload();
  await page.getByRole("button", { name: "Планы" }).click();
  await expect(page.getByTestId("plan-week-progress").first()).toHaveText(/Текущая неделя · [1-9]\d* из \d+/);

  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});
