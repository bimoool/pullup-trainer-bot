import { expect, test } from "@playwright/test";

import { noWakeLock } from "../fixtures/builderFlow";
import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py analytics_v2 910003 — часовой пояс Pacific/Kiritimati,
// 205 старых сессий "Подтягиваний" (reps), смешанная (pull reps -> Бёрпи
// interval -> pull max), time, max (новый рекорд), граничная сессия в
// понедельник текущей ЛОКАЛЬНОЙ недели 00:30. В окне 30 дней ровно 4 сессии.
const TELEGRAM_ID = 910_003;

test.describe.configure({ mode: "serial" });

test("Analytics v2: активность, панели протоколов, разделение reps/max, >200 сессий", async ({ page }) => {
  const { consoleErrors } = await openAppAs(page, TELEGRAM_ID);
  await page.getByRole("button", { name: "Аналитика" }).click();

  // По умолчанию — "Тренировки"; Программа не показана.
  await expect(page.getByRole("tab", { name: "Тренировки", selected: true })).toBeVisible();
  await expect(page.getByText("📈 График")).toHaveCount(0);

  // 30 дней: ровно 4 сессии в 4 разных локальных днях.
  const activity = page.locator(".analytics-activity-cards");
  await expect(activity.locator(".analytics-stat").filter({ hasText: "Тренировок за 30 дней" })).toContainText("4");
  await expect(activity.locator(".analytics-stat").filter({ hasText: "Активных дней" })).toContainText("4");

  // 12 недель (с понедельника): граничная сессия попала в ТЕКУЩУЮ локальную неделю, а не в прошлую.
  const label = (await page.locator(".analytics-weeks-chart").getAttribute("aria-label")) ?? "";
  const entries = label.split(": ").slice(1).join(": ").split(", ");
  expect(entries).toHaveLength(12);
  expect(entries[entries.length - 1]).toMatch(/: 1$/);

  // Селектор упражнений; по умолчанию первое (Бёрпи -> интервалы).
  await expect(page.getByRole("button", { name: "Бёрпи" })).toBeVisible();
  await expect(page.locator('[data-protocol="interval"]')).toContainText("1:00");
  await expect(page.locator('[data-protocol="interval"]')).toContainText("Интервалов");

  await page.getByRole("button", { name: "Планка" }).click();
  const time = page.locator('[data-protocol="time_sets"]');
  await expect(time).toContainText("0:55"); // 30 + 25 секунд
  await expect(time).toContainText("Лучшая длительность");
  await expect(page.locator('[data-protocol="reps_sets"]')).toHaveCount(0);

  // Подтягивания: reps и max — ОТДЕЛЬНЫЕ панели, не суммируются.
  await page.getByRole("button", { name: "Подтягивания" }).click();
  const reps = page.locator('[data-protocol="reps_sets"]');
  const max = page.locator('[data-protocol="max_effort"]');
  await expect(reps).toContainText("1865"); // 205*9 + 15 + 5 — все 207 сессий, не страницы Журнала
  await expect(reps).toContainText("413"); // подходов
  await expect(reps).toContainText("Показаны последние 30 из 207");
  await expect(reps.locator("svg.analytics-trend-chart circle")).toHaveCount(30); // ограниченный график
  await expect(max).toContainText("Максимум повторений");
  await expect(max).toContainText("21"); // лучший результат (19 -> 21: новый рекорд)
  await expect(max).not.toContainText("1865");
  await expect(max.locator("svg.analytics-trend-chart circle")).toHaveCount(2);
  await expect(max.locator('svg.analytics-trend-chart circle[fill="#eb6834"]')).toHaveCount(1); // ◆ новый рекорд

  // Ничего сырого/технического.
  await expect(page.locator(".analytics-panel").filter({ hasText: /\.00|reps_sets|max_effort|undefined|NaN|null/ })).toHaveCount(0);

  // Программа остаётся доступной.
  await page.getByRole("tab", { name: "Программа" }).click();
  await expect(page.getByRole("button", { name: "📈 График" })).toBeVisible();

  expect(noWakeLock(consoleErrors)).toEqual([]);
});

test("Analytics v2: ошибка не блокирует «Программу»; повтор работает", async ({ page }) => {
  let fail = true;
  await page.route("**/api/v2/analytics/training", async (route) => {
    if (fail) {
      fail = false;
      await route.fulfill({ status: 500, body: "boom" });
    } else {
      await route.continue();
    }
  });
  await openAppAs(page, TELEGRAM_ID, { allowedApiStatuses: [500] });
  await page.getByRole("button", { name: "Аналитика" }).click();

  await expect(page.getByText(/Не удалось загрузить аналитику тренировок/)).toBeVisible();
  await page.getByRole("tab", { name: "Программа" }).click();
  await expect(page.getByRole("button", { name: "📈 График" })).toBeVisible();

  await page.getByRole("tab", { name: "Тренировки" }).click();
  await expect(page.locator(".analytics-activity-cards")).toBeVisible(); // повторная загрузка прошла
});

for (const width of [320, 390]) {
  test(`Analytics v2: ${width}px без горизонтального скролла`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await openAppAs(page, TELEGRAM_ID);
    await page.getByRole("button", { name: "Аналитика" }).click();
    await page.getByRole("button", { name: "Подтягивания" }).click();
    await expect(page.locator('[data-protocol="reps_sets"]')).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
}
