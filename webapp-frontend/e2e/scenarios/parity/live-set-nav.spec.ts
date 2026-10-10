import { expect, test, type Page } from "@playwright/test";

import { clickAndSync, noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, WIDTHS } from "../../fixtures/parity";
import { openAppAs, useLiveEngineV1 } from "../../fixtures/setup";
import type { TelegramTheme } from "../../fixtures/telegramMock";

// issue #306: сценарий экрана движка v1 (сессии engine_version = 1) — новые старты здесь на v1.
useLiveEngineV1(test);

// #292 «Предыдущий подход» в Live: шаг назад переоткрывает предыдущий подход (SetLog не удаляется,
// повторное «Готово» перезаписывает ту же строку), недоступен на границе блока и офлайн/при очереди.
// «Пропустить подход» сознательно не делается (нужно решение владельца о прогрессии, см. #292).
// Seed: session_recovery (3 x 8, отдых 60 с); 9929xx на ширину × тему, на тест id + 2*индекс + retry.
const TITLE = "Тренировка восстановления";
const USERS: Record<number, Record<TelegramTheme, number>> = {
  320: { light: 992_901, dark: 992_911 },
  390: { light: 992_921, dark: 992_931 },
};
const RESULT = /Результат|Секунды|Повторений/;
const PREV = "Предыдущий подход";

async function startLive(page: Page) {
  await page.getByTestId("my-workout-card").filter({ hasText: TITLE }).click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await page.getByRole("button", { name: "Свободный пул" }).click();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  const group = page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${TITLE}`) });
  await group.getByRole("button", { name: /^Начать: / }).click();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
}

const phase = (page: Page, name: string) => page.getByRole("heading", { name, exact: true, level: 2 });

async function logSet(page: Page, reps: string) {
  await page.getByLabel(RESULT).fill(reps);
  await clickAndSync(page, "Готово", "/sets:batch");
}

async function finishAndExpect(page: Page, expected: string[]) {
  await page.getByRole("button", { name: "Завершить", exact: true }).click();
  await clickAndSync(page, "Сохранить и завершить", "/complete");
  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  for (const line of expected) {
    await expect(page.getByText(line)).toBeVisible();
  }
}

for (const width of WIDTHS) {
  for (const theme of ["light", "dark"] as TelegramTheme[]) {
    test.describe(`Live set nav @${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: width === 320 ? 640 : 844 } });
      test.setTimeout(150_000);

      test("с отдыха: назад открывает тот же подход со значением, повторное «Готово» перезаписывает без дублей", async ({ page }, testInfo) => {
        page.on("dialog", (dialog) => void dialog.accept());
        const { consoleErrors, apiFailures } = await openAppAs(page, USERS[width][theme] + testInfo.retry, { theme });
        await startLive(page);

        // Граница: на «Приготовься» первого подхода и в «Пошёл» первого подхода назад недоступен.
        const prev = page.getByRole("button", { name: PREV, exact: true });
        await expect(phase(page, "Приготовься")).toBeVisible();
        await expect(prev).toBeDisabled();
        await clickAndSync(page, "Готов", "/phase/next");
        await expect(phase(page, "Пошёл")).toBeVisible();
        await expect(prev).toBeDisabled();

        await logSet(page, "8");
        await expect(phase(page, "Отдых")).toBeVisible();
        await expect(prev).toBeEnabled();
        const box = (await prev.boundingBox())!;
        expect(box.width, "≥44 px по ширине").toBeGreaterThanOrEqual(44);
        expect(box.height, "≥44 px по высоте").toBeGreaterThanOrEqual(44);
        const viewport = page.viewportSize()!;
        expect(box.y + box.height, "в окне без прокрутки").toBeLessThanOrEqual(viewport.height);
        await expectNoHorizontalOverflow(page, "Live: кнопка «Предыдущий подход»");

        await clickAndSync(page, PREV, "/phase/back");
        await expect(phase(page, "Пошёл")).toBeVisible();
        await expect(page.getByLabel(RESULT)).toHaveValue("8");
        await expectNoHorizontalOverflow(page, "Live: после «назад»");
        await logSet(page, "11");
        await expect(phase(page, "Отдых")).toBeVisible();

        await clickAndSync(page, "Пропустить отдых", "/phase/next");
        await clickAndSync(page, "Готов", "/phase/next");
        await logSet(page, "7");
        await clickAndSync(page, "Пропустить отдых", "/phase/next");
        await clickAndSync(page, "Готов", "/phase/next");
        await logSet(page, "6");
        await finishAndExpect(page, ["Подход 1: 11 повт.", "Подход 2: 7 повт.", "Подход 3: 6 повт."]);
        await expect(page.getByText("Подход 1: 8 повт.")).toHaveCount(0);

        expect(noWakeLock(consoleErrors)).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("с «Приготовься» следующего подхода: назад к предыдущему, без правки — итог прежний, потерь нет", async ({ page }, testInfo) => {
        page.on("dialog", (dialog) => void dialog.accept());
        const { consoleErrors, apiFailures } = await openAppAs(page, USERS[width][theme] + 2 + testInfo.retry, { theme });
        await startLive(page);
        await clickAndSync(page, "Готов", "/phase/next");
        await logSet(page, "8");
        await clickAndSync(page, "Пропустить отдых", "/phase/next");
        await expect(phase(page, "Приготовься")).toBeVisible();

        await clickAndSync(page, PREV, "/phase/back");
        await expect(phase(page, "Пошёл")).toBeVisible();
        await expect(page.getByLabel(RESULT)).toHaveValue("8");
        // Перезагрузка посреди «возврата»: состояние с сервера, значение подхода на месте.
        await page.reload();
        await expect(phase(page, "Пошёл")).toBeVisible();
        await expect(page.getByLabel(RESULT)).toHaveValue("8");

        await logSet(page, "8"); // без правки
        await clickAndSync(page, "Пропустить отдых", "/phase/next");
        await clickAndSync(page, "Готов", "/phase/next");
        await logSet(page, "9");
        await clickAndSync(page, "Пропустить отдых", "/phase/next");
        await clickAndSync(page, "Готов", "/phase/next");
        await logSet(page, "7");
        // На итоговом «Завершить» назад возвращает последний подход — тоже без потерь.
        await expect(page.getByRole("button", { name: "Завершить", exact: true })).toBeVisible();
        await clickAndSync(page, PREV, "/phase/back");
        await expect(phase(page, "Пошёл")).toBeVisible();
        await expect(page.getByLabel(RESULT)).toHaveValue("7");
        await logSet(page, "7");
        await finishAndExpect(page, ["Подход 1: 8 повт.", "Подход 2: 9 повт.", "Подход 3: 7 повт."]);

        expect(noWakeLock(consoleErrors)).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("офлайн и при очереди: «Предыдущий подход» недоступен, данные не теряются, сеть вернулась — работает", async ({ page, context }, testInfo) => {
        page.on("dialog", (dialog) => void dialog.accept());
        const { consoleErrors } = await openAppAs(page, USERS[width][theme] + 4 + testInfo.retry, { theme });
        await startLive(page);
        await clickAndSync(page, "Готов", "/phase/next");
        const prev = page.getByRole("button", { name: PREV, exact: true });

        // Подход записан без сети: в очереди — назад отключён (подсказка про сеть).
        await context.setOffline(true);
        await page.getByLabel(RESULT).fill("8");
        await page.getByRole("button", { name: "Готово", exact: true }).click();
        await expect(phase(page, "Отдых")).toBeVisible();
        await expect(prev).toBeDisabled();
        await expect(prev).toHaveAttribute("title", "Нужна сеть");

        // Сеть вернулась: очередь уходит сама, затем назад доступен и данные на месте.
        const synced = page.waitForResponse((r) => r.url().includes("/sets:batch") && r.status() === 200);
        await context.setOffline(false);
        await synced;
        await expect(prev).toBeEnabled();
        await clickAndSync(page, PREV, "/phase/back");
        await expect(phase(page, "Пошёл")).toBeVisible();
        await expect(page.getByLabel(RESULT)).toHaveValue("8");
        await logSet(page, "8");
        await clickAndSync(page, "Пропустить отдых", "/phase/next");
        await clickAndSync(page, "Готов", "/phase/next");
        await logSet(page, "5");
        await clickAndSync(page, "Пропустить отдых", "/phase/next");
        await clickAndSync(page, "Готов", "/phase/next");
        await logSet(page, "4");
        await finishAndExpect(page, ["Подход 1: 8 повт.", "Подход 2: 5 повт.", "Подход 3: 4 повт."]);

        expect(noWakeLock(consoleErrors)).toEqual([]);
      });
    });
  }
}
