import { expect, test, type Locator, type Page } from "@playwright/test";

import { clickAndSync, noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import type { TelegramTheme } from "../../fixtures/telegramMock";

// CRIMPD VISUAL (#280, Live Session): язык полноэкранного плеера — огромный таймер, подпись
// состояния (<h2>), одно главное действие внизу экрана без прокрутки, шторка итога, итоговый
// экран с главным CTA. Проверяем геометрию, не пиксели: размер шрифта таймера, видимость
// главного действия в окне 320×640 без прокрутки, отсутствие горизонтального overflow.
// Seed: scripts/e2e_seed.py session_recovery — Workout «Тренировка восстановления», reps 3 x 8,
// отдых 60 с; 9976xx по пользователю на ширину × тему и + retry (id+1).
const TITLE = "Тренировка восстановления";
const USERS: Record<number, Record<TelegramTheme, number>> = {
  320: { light: 997_601, dark: 997_611 },
  390: { light: 997_621, dark: 997_631 },
};
const MIN_TIMER_PX = 64;

async function expectInWindow(page: Page, target: Locator, what: string) {
  const box = await target.boundingBox();
  const viewport = page.viewportSize();
  expect(box, `${what}: нет геометрии`).not.toBeNull();
  expect(box!.y, `${what}: выше окна`).toBeGreaterThanOrEqual(0);
  expect(box!.y + box!.height, `${what}: ниже окна (нужна прокрутка)`).toBeLessThanOrEqual(viewport!.height);
  expect(box!.x + box!.width, `${what}: шире окна`).toBeLessThanOrEqual(viewport!.width);
}

async function expectTimerLarge(page: Page, where: string) {
  const timer = page.locator(".timer-duration-label").first();
  await expect(timer).toBeVisible();
  const size = await timer.evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
  expect(size, `таймер на «${where}» мельче ${MIN_TIMER_PX}px`).toBeGreaterThanOrEqual(MIN_TIMER_PX);
}

async function expectNotScrolled(page: Page) {
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
}

for (const width of WIDTHS) {
  for (const theme of ["light", "dark"] as TelegramTheme[]) {
    test.describe(`Visual live @${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: width === 320 ? 640 : 844 } });
      test.setTimeout(120_000);

      test("плеер: огромный таймер, главное действие без прокрутки, шторка итога, итоговый экран", async ({ page }, testInfo) => {
        page.on("dialog", (dialog) => void dialog.accept());
        const { consoleErrors, apiFailures } = await openAppAs(page, USERS[width][theme] + testInfo.retry, { theme });

        // Старт из свободного пула «Планов».
        await page.getByTestId("my-workout-card").filter({ hasText: TITLE }).click();
        await page.getByRole("button", { name: "Добавить в план" }).click();
        await page.getByRole("button", { name: "Свободный пул" }).click();
        await page.getByRole("button", { name: "Добавить", exact: true }).click();
        const group = page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${TITLE}`) });
        await group.getByRole("button", { name: "Начать", exact: true }).click();
        await page.getByRole("button", { name: "Начать", exact: true }).click(); // SessionPreScreen
        await expect(page.getByText("Живая тренировка")).toBeVisible();

        // Приготовиться: состояние — <h2>, таймер огромный, «Готов» под рукой.
        await expect(page.getByRole("heading", { name: "Приготовься", exact: true, level: 2 })).toBeVisible();
        await expectTimerLarge(page, "Приготовься");
        await expectNotScrolled(page);
        await expectInWindow(page, page.getByRole("button", { name: "Готов", exact: true }), "«Готов»");
        await expect(page.getByText(/Подход 1\/3 · Цель: 8 повт\./)).toBeVisible();
        await expectNoHorizontalOverflow(page, "Live: приготовиться");

        // Работа: крупная цель вместо таймера, поле записи и «Готово» в окне; оценка раскрывается.
        await clickAndSync(page, "Готов", "/phase/next");
        await expect(page.getByRole("heading", { name: "Пошёл", exact: true, level: 2 })).toBeVisible();
        await expectNotScrolled(page);
        await expectInWindow(page, page.getByRole("button", { name: "Готово", exact: true }), "«Готово»");
        await expectInWindow(page, page.getByLabel(/Результат|Секунды|Повторений/), "поле результата");
        const hero = await page.locator(".live-hero-target").evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
        expect(hero).toBeGreaterThanOrEqual(MIN_TIMER_PX - 12);
        await expectNoHorizontalOverflow(page, "Live: работа");
        await page.getByLabel(/Результат|Секунды|Повторений/).fill("8");
        await page.getByTestId("log-panel-toggle").click();
        await expect(page.getByTestId("set-effort").getByRole("button")).toHaveCount(5);
        await expectNoHorizontalOverflow(page, "Live: работа, панель оценки");
        await expectInWindow(page, page.getByRole("button", { name: "Готово", exact: true }), "«Готово» при раскрытой оценке");

        // Отдых 60 с: таймер огромный, «Пропустить отдых» и «Пауза» закреплены внизу.
        await clickAndSync(page, "Готово", "/sets:batch");
        await expect(page.getByRole("heading", { name: "Отдых", exact: true, level: 2 })).toBeVisible();
        await expectTimerLarge(page, "Отдых");
        await expectInWindow(page, page.getByRole("button", { name: "Пропустить отдых", exact: true }), "«Пропустить отдых»");
        await expectInWindow(page, page.getByTestId("pause-toggle"), "«Пауза»");
        await expectNoHorizontalOverflow(page, "Live: отдых");
        await page.getByTestId("pause-toggle").click();
        await expect(page.getByTestId("pause-toggle")).toHaveText("Продолжить");
        await expectNoHorizontalOverflow(page, "Live: пауза");
        await page.getByTestId("pause-toggle").click();

        // Остальные подходы → план выполнен: «Завершить» — главное действие.
        for (const reps of ["7", "6"]) {
          await clickAndSync(page, "Пропустить отдых", "/phase/next");
          await clickAndSync(page, "Готов", "/phase/next");
          await page.getByLabel(/Результат|Секунды|Повторений/).fill(reps);
          await clickAndSync(page, "Готово", "/sets:batch");
        }
        await expect(page.getByText("Все подходы плана выполнены — можно завершить сессию.")).toBeVisible();
        await expectInWindow(page, page.getByRole("button", { name: "Завершить", exact: true }), "«Завершить»");
        await expectNoHorizontalOverflow(page, "Live: план выполнен");

        // Шторка итога: целиком в окне, пять сегментов, «Сохранить и завершить» достижима.
        await page.getByRole("button", { name: "Завершить", exact: true }).click();
        const review = page.getByTestId("workout-review");
        await expect(review).toContainText("Как прошла тренировка?");
        await expectInWindow(page, review, "шторка итога");
        await expectInWindow(page, review.getByRole("button", { name: "Сохранить и завершить" }), "«Сохранить и завершить»");
        await expectNoHorizontalOverflow(page, "Live: шторка итога");

        // Итоговый экран: «Закрыть» в окне, без overflow.
        await review.getByTestId("workout-effort").getByRole("button").nth(2).click();
        await clickAndSync(page, "Сохранить и завершить", "/complete");
        await expect(page.getByText("Тренировка завершена")).toBeVisible();
        await expect(page.getByText("Подход 1: 8 повт.")).toBeVisible();
        await expectInWindow(page, page.getByRole("button", { name: "Закрыть", exact: true }), "«Закрыть»");
        await expectNoHorizontalOverflow(page, "Live: итог");

        expect(noWakeLock(consoleErrors)).toEqual([]);
        expect(apiFailures).toEqual([]);
      });
    });
  }
}
