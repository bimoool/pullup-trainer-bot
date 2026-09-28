import { expect, type Page, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py builder_workouts 910001 — шесть пользовательских Builder
// Workout текущей недели: по одному на протокол, смешанная (reps -> interval
// -> max) и "Дубли" (одно упражнение дважды). Интервал — 15 с (5 с работа /
// 5 с отдых), отдых между подходами — 2 с.
const TELEGRAM_ID = 910_001;

// Один пользователь — одна активная сессия за раз.
test.describe.configure({ mode: "serial" });
test.setTimeout(120_000);

async function startWorkout(page: Page, title: string) {
  await page.getByRole("button", { name: "Планы" }).click();
  const group = page.locator(".plan-week-day-group").filter({ has: page.getByText(title, { exact: false }) })
    .filter({ hasText: new RegExp(`^${title}`) });
  await group.getByRole("button", { name: "Начать", exact: true }).click();
  await page.getByRole("button", { name: "Начать", exact: true }).click(); // SessionPreScreen
  await expect(page.getByText("Живая тренировка")).toBeVisible();
}

/** Клик + ожидание ответа сервера: повторный тап во время уже идущего
 * запроса приложение намеренно отбрасывает (guardedAction). */
async function clickAndSync(page: Page, name: string, urlPart: string) {
  const response = page.waitForResponse((r) => r.url().includes(urlPart) && r.status() === 200);
  await page.getByRole("button", { name, exact: true }).click();
  await response;
}

/** Один обычный блок целиком: подходы с отдыхом; после последнего подхода
 * не трогает ничего. */
async function playSets(page: Page, values: string[], rest = true) {
  for (let i = 0; i < values.length; i += 1) {
    await clickAndSync(page, "Готов", "/phase/next");
    await expect(page.getByText("Пошёл")).toBeVisible();
    await page.getByLabel(/Результат|Секунды|Повторений/).fill(values[i]);
    await clickAndSync(page, "Готово", "/sets:batch");
    if (i < values.length - 1 && rest) {
      await clickAndSync(page, "Пропустить отдых", "/phase/next");
    }
  }
}

// Headless Chromium не даёт Wake Lock — шум окружения, не баг приложения.
const noWakeLock = (errors: string[]) => errors.filter((e) => !e.includes("Wake Lock"));

test("A. reps standalone: цели из prescription, Summary после последнего блока", async ({ page }) => {
  page.on("dialog", (dialog) => void dialog.accept());
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);
  await startWorkout(page, "Только reps");

  await expect(page.getByText(/Подход 1\/2 · Цель: 8 повт\./)).toBeVisible(); // не 9 подходов legacy
  await playSets(page, ["8", "7"]);
  await expect(page.getByText("Все подходы плана выполнены")).toBeVisible();
  await page.getByRole("button", { name: "Завершить" }).click();

  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  await expect(page.getByText("Подход 1: 8 повт.")).toBeVisible();
  await expect(page.getByText(/\.00|\d reps/)).toHaveCount(0);
  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});

test("B. time standalone: секунды, цель 0:30", async ({ page }) => {
  page.on("dialog", (dialog) => void dialog.accept());
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);
  await startWorkout(page, "Только time");

  await expect(page.getByText(/Подход 1\/2 · Цель: 0:30/)).toBeVisible();
  await clickAndSync(page, "Готов", "/phase/next");
  await expect(page.getByLabel("Секунды")).toHaveValue("30"); // предзаполнено целью
  await page.getByLabel("Секунды").fill("28");
  await clickAndSync(page, "Готово", "/sets:batch");
  await clickAndSync(page, "Пропустить отдых", "/phase/next");
  await playSets(page, ["30"]);
  await page.getByRole("button", { name: "Завершить" }).click();

  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  await expect(page.getByText("Подход 1: 0:28")).toBeVisible();
  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});

test("C. max standalone: попытки без выдуманной цели", async ({ page }) => {
  page.on("dialog", (dialog) => void dialog.accept());
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);
  await startWorkout(page, "Только max");

  await expect(page.getByText(/Попытка 1\/2 · Максимум/)).toBeVisible();
  await expect(page.getByText(/Цель/)).toHaveCount(0);
  await playSets(page, ["20", "22"]);
  await page.getByRole("button", { name: "Завершить" }).click();

  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  await expect(page.getByText("Лучший результат: 22")).toBeVisible();
  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});

test("D. interval standalone: серверный таймер, автозавершение -> Summary", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);
  await startWorkout(page, "Только interval");

  await expect(page.getByText("Подготовка")).toBeVisible();
  await expect(page.getByText("Работа").first()).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("Тренировка завершена")).toBeVisible({ timeout: 40_000 });
  await expect(page.getByText("0:15 выполнено")).toBeVisible();
  await expect(page.getByText("2 интервала")).toBeVisible();
  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});

test("E. mixed reps -> interval -> max: ручные переходы, reload, истечение interval, дубль-старт, retry", async ({ page }) => {
  page.on("dialog", (dialog) => void dialog.accept());
  const { consoleErrors } = await openAppAs(page, TELEGRAM_ID);
  const blockStarts: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/blocks/start")) {
      blockStarts.push(request.url());
    }
  });
  await startWorkout(page, "Смешанная");

  // --- Блок 0 (reps): конец блока НЕ стартует следующий сам ---
  await playSets(page, ["8", "8"]);
  await expect(page.getByText("Готово ✓")).toBeVisible();
  await expect(page.getByText("Следующее упражнение")).toBeVisible();
  await expect(page.getByText("Бёрпи · 0:15 · 5/5 сек")).toBeVisible();
  await expect(page.getByText("Тренировка завершена")).toHaveCount(0); // Summary не раньше последнего блока
  await expect(page.getByRole("button", { name: "Пропустить" })).toHaveCount(0);

  // --- reload, пока следующий блок не начат: interstitial восстановился ---
  await page.reload({ waitUntil: "networkidle" });
  await expect(page.getByText("Следующее упражнение")).toBeVisible();
  await expect(page.getByText("Бёрпи · 0:15 · 5/5 сек")).toBeVisible();
  await expect(page.getByText("Подготовка")).toHaveCount(0); // interval ещё не идёт

  // --- retry: первый blocks/start падает, кнопка остаётся, второй проходит ---
  let failNext = true;
  await page.route("**/api/v2/sessions/live/*/blocks/start", async (route) => {
    if (failNext) {
      failNext = false;
      await route.fulfill({ status: 500, body: "boom" });
    } else {
      await route.continue();
    }
  });
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await expect(page.getByText(/Не удалось начать/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Начать", exact: true })).toBeEnabled();

  // --- двойной клик по Начать: блок стартует ровно один раз ---
  const before = blockStarts.length;
  await page.getByRole("button", { name: "Начать", exact: true }).dblclick();
  await expect(page.getByText("Подготовка")).toBeVisible();
  expect(blockStarts.length - before).toBe(1);

  // --- reload посреди активного interval: серверное время, не сброс ---
  await page.waitForTimeout(6_000);
  await page.reload({ waitUntil: "networkidle" });
  await expect(page.getByText(/Работа|Отдых/).first()).toBeVisible();
  await expect(page.getByText("Следующее упражнение")).toHaveCount(0);

  // --- истечение interval в СЕРЕДИНЕ: interstitial max-блока, не Summary ---
  await expect(page.getByText("Следующее упражнение")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Отжимания · Максимум · 2 попытки")).toBeVisible();
  await expect(page.getByText("Тренировка завершена")).toHaveCount(0);

  // --- блок 2 (max), затем Summary с тремя независимыми блоками ---
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await expect(page.getByText(/Попытка 1\/2 · Максимум/)).toBeVisible();
  await playSets(page, ["18", "22"]);
  await page.getByRole("button", { name: "Завершить" }).click();

  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  await expect(page.getByText(/Подтягивания — 2\/2/)).toBeVisible();
  await expect(page.getByText("2 интервала")).toBeVisible();
  await expect(page.getByText("Лучший результат: 22")).toBeVisible();
  expect(noWakeLock(consoleErrors).filter((e) => !e.includes("500"))).toEqual([]);
});

test("F. дубли упражнения: подходы второго блока не попадают в первый", async ({ page }) => {
  page.on("dialog", (dialog) => void dialog.accept());
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);
  await startWorkout(page, "Дубли");

  await playSets(page, ["8", "8"]); // Подтягивания (reps) — блок 0
  await page.getByRole("button", { name: "Начать", exact: true }).click(); // Планка
  await playSets(page, ["30", "30"]);
  await page.getByRole("button", { name: "Начать", exact: true }).click(); // Подтягивания (max) — блок 2
  await playSets(page, ["15", "17"]);
  await page.getByRole("button", { name: "Завершить" }).click();

  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  await expect(page.getByText(/Подтягивания — 2\/2/)).toHaveCount(2); // оба блока сохранили свои подходы
  await expect(page.getByText("Подход 1: 8 повт.")).toBeVisible();
  await expect(page.getByText("Попытка 2: 17 повт.")).toBeVisible();
  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});
