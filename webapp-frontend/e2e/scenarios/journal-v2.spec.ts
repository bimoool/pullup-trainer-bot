import { expect, test } from "@playwright/test";

import { clickAndSync, noWakeLock, playSets, startWorkout } from "../fixtures/builderFlow";
import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py journal_v2 910002 — Builder Workout (как builder_workouts)
// + 30 завершённых "исторических" сессий без снимка (их удалять нельзя).
const TELEGRAM_ID = 910_002;

test.describe.configure({ mode: "serial" });
test.setTimeout(120_000);

test("Journal v2: карточки всех протоколов, детали, безопасное удаление, пагинация", async ({ page }) => {
  page.on("dialog", (dialog) => void dialog.accept());
  const { consoleErrors } = await openAppAs(page, TELEGRAM_ID);

  // --- Наполняем журнал реальными тренировками: time и смешанная ---
  await startWorkout(page, "Только time");
  await playSets(page, ["30", "25"]);
  await page.getByRole("button", { name: "Завершить" }).click();
  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  await page.getByRole("button", { name: "Закрыть" }).click();

  await startWorkout(page, "Смешанная");
  await playSets(page, ["8", "7"]);
  await clickAndSync(page, "Начать", "/blocks/start");
  await expect(page.getByText("Следующее упражнение")).toBeVisible({ timeout: 40_000 }); // interval истёк
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await playSets(page, ["18", "22"]);
  await page.getByRole("button", { name: "Завершить" }).click();
  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  await page.getByRole("button", { name: "Закрыть" }).click();

  // --- Журнал: каждый блок независимо, человекочитаемо ---
  await page.getByRole("button", { name: "Журнал" }).click();
  const mixed = page.locator(".history-card").filter({ hasText: "Смешанная" });
  await expect(mixed).toBeVisible();
  await expect(mixed.getByText("Подтягивания", { exact: true })).toBeVisible();
  await expect(mixed.getByText("8 · 7", { exact: true })).toBeVisible();
  await expect(mixed.getByText("Бёрпи · Интервалы")).toBeVisible();
  await expect(mixed.getByText("0:15 · 2 интервала")).toBeVisible();
  await expect(mixed.getByText("Отжимания · Максимум повторений")).toBeVisible();
  await expect(mixed.getByText("2 попытки · лучший 22")).toBeVisible();
  const timeCard = page.locator(".history-card").filter({ hasText: "Только time" });
  await expect(timeCard.getByText("Планка", { exact: true })).toBeVisible();
  await expect(timeCard.getByText("0:30 · 0:25", { exact: true })).toBeVisible();
  await expect(page.locator(".history-card").filter({ hasText: /\.00|reps|"type"|Упражнение #/ })).toHaveCount(0);

  // --- Пагинация: первая страница 25, "Показать ещё" дозагружает без дублей ---
  await expect(page.locator(".history-card-clickable")).toHaveCount(25);
  let sessionRequests = 0;
  page.on("request", (request) => {
    if (request.url().includes("/api/v2/sessions?")) {
      sessionRequests += 1;
    }
  });
  // сбой догрузки не стирает уже загруженное
  let failNext = true;
  await page.route("**/api/v2/sessions?*offset=25*", async (route) => {
    if (failNext) {
      failNext = false;
      await route.fulfill({ status: 500, body: "boom" });
    } else {
      await route.continue();
    }
  });
  await page.getByRole("button", { name: "Показать ещё" }).click();
  await expect(page.getByText(/Не удалось загрузить ещё/)).toBeVisible();
  await expect(page.locator(".history-card-clickable")).toHaveCount(25);
  // двойной клик — ровно один запрос догрузки
  const before = sessionRequests;
  await page.getByRole("button", { name: "Показать ещё" }).dblclick();
  await expect(page.locator(".history-card-clickable")).toHaveCount(32);
  expect(sessionRequests - before).toBe(1);
  await expect(page.getByRole("button", { name: "Показать ещё" })).toHaveCount(0);

  // --- Детали: из уже загруженного объекта (запросов нет), Back сохраняет состояние ---
  const requestsBeforeDetail = sessionRequests;
  await mixed.click();
  await expect(page.getByText("Подходы с повторениями")).toBeVisible();
  await expect(page.getByText("План: 8 · 8")).toBeVisible();
  await expect(page.getByText("Факт: 8 · 7")).toBeVisible();
  await expect(page.getByText("Интервалы", { exact: true })).toBeVisible();
  await expect(page.getByText("План: 0:15 · 5/5 сек")).toBeVisible();
  await expect(page.getByText("Максимум", { exact: true })).toBeVisible();
  await expect(page.getByText("Факт: 2 попытки · лучший 22")).toBeVisible();
  await expect(page.getByRole("button", { name: /Удалить/ })).toBeVisible(); // Builder — can_delete
  expect(sessionRequests).toBe(requestsBeforeDetail);
  await page.getByRole("button", { name: "← Назад" }).click();
  await expect(page.locator(".history-card-clickable")).toHaveCount(32); // без перезагрузки списка
  expect(sessionRequests).toBe(requestsBeforeDetail);

  // --- Историческая сессия без снимка: удалить нельзя (решает бэкенд) ---
  await page.locator(".history-card-clickable").last().click();
  await expect(page.getByRole("button", { name: /Удалить/ })).toHaveCount(0);
  await page.getByRole("button", { name: "← Назад" }).click();

  // --- Безопасное удаление: двойной клик -> один DELETE; следующий offset не ломается ---
  const deleteRequests: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "DELETE" && request.url().includes("/api/v2/sessions/")) {
      deleteRequests.push(request.url());
    }
  });
  await timeCard.click();
  await page.getByRole("button", { name: /Удалить/ }).dblclick();
  await expect(page.locator(".history-card-clickable")).toHaveCount(31);
  await expect(page.locator(".history-card").filter({ hasText: "Только time" })).toHaveCount(0);
  expect(deleteRequests).toHaveLength(1);

  // Свежая загрузка журнала совпадает со списком после удаления (нет дублей/дыр).
  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Журнал" }).click();
  await expect(page.locator(".history-card-clickable")).toHaveCount(25);
  await page.getByRole("button", { name: "Показать ещё" }).click();
  await expect(page.locator(".history-card-clickable")).toHaveCount(31);

  expect(noWakeLock(consoleErrors).filter((e) => !e.includes("500"))).toEqual([]);
});
