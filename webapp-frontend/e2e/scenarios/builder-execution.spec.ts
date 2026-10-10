import { expect, test } from "@playwright/test";

import { finishV2, noWakeLock, playSetsV2, startWorkout } from "../fixtures/builderFlow";
import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py builder_workouts 910001 — шесть пользовательских Builder
// Workout текущей недели: по одному на протокол, смешанная (reps -> interval
// -> max) и "Дубли" (одно упражнение дважды). Интервал — 15 с (5 с работа /
// 5 с отдых), отдых между подходами — 2 с.
//
// issue #306 (Live Engine v2): блоки сменяются сами по дедлайну отдыха блока (T2, вместо interstitial
// «Начать» R1, PROJECT_SPEC §2.5); здесь ожидание сокращается необязательным «Начать сейчас» — сами
// автопереходы реальным временем проверяет live-engine-v2.spec.ts.
const TELEGRAM_ID = 910_001;

// Один пользователь — одна активная сессия за раз.
test.describe.configure({ mode: "serial" });
test.setTimeout(120_000);

test("A. reps standalone: цели из prescription, Summary после последнего блока", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);
  await startWorkout(page, "Только reps");

  await expect(page.getByTestId("engine-target")).toHaveText(/Подход 1\/2 · Цель: 8 повт\./); // не 9 подходов legacy
  await playSetsV2(page, ["8", "7"]);
  await finishV2(page);

  await expect(page.getByText("Тренировка завершена").first()).toBeVisible();
  await expect(page.getByText("Подход 1: 8 повт.")).toBeVisible();
  await expect(page.getByText(/\.00|\d reps/)).toHaveCount(0);
  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});

test("B. time standalone: таймер работы от сервера, «Стоп» записывает измеренное", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);
  await startWorkout(page, "Только time");

  await expect(page.getByTestId("engine-target")).toHaveText(/Подход 1\/2 · Цель: 0:30/);
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл", { timeout: 10_000 }); // подготовка — сама
  await expect(page.getByTestId("engine-timer")).toBeVisible(); // обратный отсчёт работы
  await page.getByTestId("engine-stop").click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых");
  await page.getByTestId("engine-skip").click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл");
  await page.getByTestId("engine-stop").click();
  await finishV2(page);

  await expect(page.getByText("Тренировка завершена").first()).toBeVisible();
  await expect(page.getByText(/Подход 1: 0:0\d/)).toBeVisible();
  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});

test("C. max standalone: попытки без выдуманной цели", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);
  await startWorkout(page, "Только max");

  await expect(page.getByTestId("engine-target")).toHaveText(/Попытка 1\/2 · Максимум/);
  await expect(page.getByText(/Цель/)).toHaveCount(0);
  await playSetsV2(page, ["20", "22"]);
  await finishV2(page);

  await expect(page.getByText("Тренировка завершена").first()).toBeVisible();
  await expect(page.getByText("Лучший результат: 22")).toBeVisible();
  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});

test("D. interval standalone: тот же движок, раунды идут сами до конца", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);
  await startWorkout(page, "Только interval");

  await expect(page.getByTestId("engine-phase")).toHaveText("Приготовься");
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл", { timeout: 10_000 });
  await expect(page.getByTestId("engine-target")).toContainText("Раунд 1/2");
  await expect(page.getByTestId("engine-complete")).toBeVisible({ timeout: 40_000 });
  await finishV2(page);
  await expect(page.getByText("Тренировка завершена").first()).toBeVisible();
  await expect(page.getByText("2 интервала")).toBeVisible();
  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});

test("E. mixed reps -> interval -> max: блоки сменяются сами, reload посреди интервала, Summary", async ({ page }) => {
  const { consoleErrors } = await openAppAs(page, TELEGRAM_ID);
  const v1Calls: string[] = [];
  page.on("request", (request) => {
    if (/\/(blocks\/start|blocks\/finish|phase\/next|sets:batch)/.test(request.url())) {
      v1Calls.push(request.url());
    }
  });
  await startWorkout(page, "Смешанная");

  // --- Блок 0 (reps) → отдых блока с превью следующего, без «Начать» ---
  await playSetsV2(page, ["8", "8"]);
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых");
  await expect(page.getByTestId("engine-next-block")).toContainText("Бёрпи");
  await expect(page.getByRole("button", { name: "Начать", exact: true })).toHaveCount(0);
  await expect(page.getByText("Тренировка завершена")).toHaveCount(0); // Summary не раньше последнего блока

  // --- reload на отдыхе блока: то же состояние с сервера ---
  await page.reload({ waitUntil: "networkidle" });
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых");
  await page.getByTestId("engine-skip").click(); // «Начать сейчас»
  await expect(page.getByTestId("engine-target")).toContainText("Раунд 1/");

  // --- reload посреди интервала: серверное время, не сброс ---
  // Намеренная пауза: серверное время интервала реально идёт, а не сбрасывается reload-ом.
  await page.waitForTimeout(6_000);
  await page.reload({ waitUntil: "networkidle" });
  await expect(page.getByTestId("engine-target")).toContainText(/Раунд [12]\//);

  // --- конец интервала в СЕРЕДИНЕ: отдых блока, затем max-блок, не Summary ---
  await expect(page.getByTestId("engine-next-block")).toContainText("Отжимания", { timeout: 30_000 });
  await expect(page.getByText("Тренировка завершена")).toHaveCount(0);
  await playSetsV2(page, ["18", "22"]);
  await finishV2(page);

  await expect(page.getByText("Тренировка завершена").first()).toBeVisible();
  await expect(page.getByText(/Подтягивания — 2\/2/)).toBeVisible();
  await expect(page.getByText("2 интервала")).toBeVisible();
  await expect(page.getByText("Лучший результат: 22")).toBeVisible();
  expect(v1Calls).toEqual([]); // сессия v2 не трогает эндпоинты движка v1
  expect(noWakeLock(consoleErrors)).toEqual([]);
});

test("F. дубли упражнения: подходы второго блока не попадают в первый", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);
  await startWorkout(page, "Дубли");

  await playSetsV2(page, ["8", "8"]); // Подтягивания (reps) — блок 0
  await page.getByTestId("engine-skip").click(); // отдых блока → Планка
  for (let i = 1; i <= 2; i += 1) {
    await expect(page.getByTestId("engine-target")).toContainText(`Подход ${i}/2 · Цель: 0:30`);
    if ((await page.getByTestId("engine-phase").textContent())?.trim() !== "Пошёл") {
      await page.getByTestId("engine-skip").click();
    }
    await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл");
    await page.getByTestId("engine-stop").click(); // Планка — подход на время
    await expect(page.getByTestId("engine-phase")).toHaveText("Отдых");
  }
  await page.getByTestId("engine-skip").click(); // отдых блока → Подтягивания (max)
  await expect(page.getByTestId("engine-target")).toContainText("Попытка 1/2");
  await playSetsV2(page, ["15", "17"]);
  await finishV2(page);

  await expect(page.getByText("Тренировка завершена").first()).toBeVisible();
  await expect(page.getByText(/Подтягивания — 2\/2/)).toHaveCount(2); // оба блока сохранили свои подходы
  await expect(page.getByText("Подход 1: 8 повт.")).toBeVisible();
  await expect(page.getByText("Попытка 2: 17 повт.")).toBeVisible();
  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});
