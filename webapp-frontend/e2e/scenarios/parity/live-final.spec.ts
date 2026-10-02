import { expect, test, type Page } from "@playwright/test";

import { clickAndSync, noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import type { TelegramTheme } from "../../fixtures/telegramMock";

// Live Session, финальный проход: (1) пред-экран «Готовы к старту» в языке плеера — иерархия названия,
// карточки упражнений с целью, единственное главное действие в закреплённом транспорте над safe area;
// (2) правка предыдущего подхода без потери данных: с отдыха и с «Приготовься» следующего подхода тот же
// set_index перезаписывает строку, лишних записей не появляется.
// Seed: session_recovery (3 x 8, отдых 60 с); 9965xx на ширину × тему, на тест id + 2*индекс + retry.
const TITLE = "Тренировка восстановления";
const USERS: Record<number, Record<TelegramTheme, number>> = {
  320: { light: 996_501, dark: 996_511 },
  390: { light: 996_521, dark: 996_531 },
};
const RESULT = /Результат|Секунды|Повторений/;

async function openPreScreen(page: Page) {
  await page.getByTestId("my-workout-card").filter({ hasText: TITLE }).click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await page.getByRole("button", { name: "Свободный пул" }).click();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  const group = page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${TITLE}`) });
  await group.getByRole("button", { name: /^Начать: / }).click();
  await expect(page.getByTestId("session-pre")).toBeVisible();
}

for (const width of WIDTHS) {
  for (const theme of ["light", "dark"] as TelegramTheme[]) {
    test.describe(`Live final @${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: width === 320 ? 640 : 844 } });
      test.setTimeout(120_000);

      test("пред-экран: иерархия, карточки упражнений, главное действие над safe area", async ({ page }, testInfo) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, USERS[width][theme] + testInfo.retry * 2, { theme });
        await openPreScreen(page);
        const pre = page.getByTestId("session-pre");

        await expect(pre.getByText("Готовы к старту")).toBeVisible();
        const titleSize = await pre.locator(".pre-title").evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
        const eyebrowSize = await pre.locator(".pre-eyebrow").evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
        expect(titleSize, "название крупнее подписи").toBeGreaterThan(eyebrowSize + 6);

        const cards = page.getByTestId("session-pre-items").locator("li");
        await expect(cards).toHaveCount(1);
        await expect(cards.first()).toContainText(/3 ?[x×] ?8|3 подхода|8/);
        const card = await cards.first().evaluate((el) => {
          const cs = getComputedStyle(el);
          return { bg: cs.backgroundColor, radius: parseFloat(cs.borderTopLeftRadius) };
        });
        expect(card.bg, "упражнение — карточка с фоном").not.toBe("rgba(0, 0, 0, 0)");
        expect(card.radius).toBeGreaterThanOrEqual(12);

        // Единственное главное действие: «Начать» в закреплённом транспорте внизу окна, без прокрутки.
        const start = page.getByRole("button", { name: "Начать", exact: true });
        await expect(start).toHaveCount(1);
        const box = (await start.boundingBox())!;
        const viewport = page.viewportSize()!;
        expect(box.height, "главная кнопка ≥ 52 px").toBeGreaterThanOrEqual(52);
        expect(box.y + box.height, "«Начать» в окне").toBeLessThanOrEqual(viewport.height);
        const transport = (await page.locator(".pre-transport").boundingBox())!;
        expect(transport.y + transport.height, "транспорт у нижнего края").toBeGreaterThanOrEqual(viewport.height - 2);
        const padBottom = await page.locator(".pre-transport").evaluate((el) => parseFloat(getComputedStyle(el).paddingBottom));
        expect(padBottom, "нижний отступ ≥ 16 px (safe area)").toBeGreaterThanOrEqual(16);
        await expectNoHorizontalOverflow(page, "Live: пред-экран");

        expect(noWakeLock(consoleErrors)).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("предыдущий подход правится с отдыха и с «Приготовься», данные не теряются", async ({ page }, testInfo) => {
        page.on("dialog", (dialog) => void dialog.accept());
        const { consoleErrors, apiFailures } = await openAppAs(page, USERS[width][theme] + 1 + testInfo.retry * 2, { theme });
        await openPreScreen(page);
        await page.getByRole("button", { name: "Начать", exact: true }).click();
        await clickAndSync(page, "Готов", "/phase/next");
        await page.getByLabel(RESULT).fill("8");
        await clickAndSync(page, "Готово", "/sets:batch");
        await expect(page.getByRole("heading", { name: "Отдых", exact: true, level: 2 })).toBeVisible();

        // Отдых: правка записанного подхода (как раньше), затем пропуск — на «Приготовься» запись видна и правится.
        await page.getByRole("button", { name: "Изменить" }).click();
        await page.getByLabel(RESULT).fill("9");
        await page.getByRole("button", { name: "Сохранить подход" }).click();
        await page.getByRole("button", { name: "Свернуть" }).click();
        await expect(page.getByTestId("log-panel-summary")).toContainText("Подход 1: 9 повт.");
        await clickAndSync(page, "Пропустить отдых", "/phase/next");
        await expect(page.getByRole("heading", { name: "Приготовься", exact: true, level: 2 })).toBeVisible();
        await expect(page.getByTestId("log-panel-summary")).toContainText("Подход 1: 9 повт.");

        await page.getByRole("button", { name: "Изменить" }).click();
        await expect(page.getByText("Подход 1: результат")).toBeVisible();
        await page.getByLabel(RESULT).fill("10");
        await page.getByRole("button", { name: "Сохранить подход" }).click();
        await page.getByRole("button", { name: "Свернуть" }).click();
        await expect(page.getByTestId("log-panel-summary")).toContainText("Подход 1: 10 повт.");
        await expectNoHorizontalOverflow(page, "Live: правка на «Приготовься»");

        // Правка не двигает фазу и не затирает следующий подход: «Готов» → новая пустая форма.
        await clickAndSync(page, "Готов", "/phase/next");
        await expect(page.getByTestId("log-panel-summary")).toHaveCount(0);
        await expect(page.getByLabel(RESULT)).toHaveValue("");
        await page.getByLabel(RESULT).fill("7");
        await clickAndSync(page, "Готово", "/sets:batch");
        for (const reps of ["6"]) {
          await clickAndSync(page, "Пропустить отдых", "/phase/next");
          await clickAndSync(page, "Готов", "/phase/next");
          await page.getByLabel(RESULT).fill(reps);
          await clickAndSync(page, "Готово", "/sets:batch");
        }
        await page.getByRole("button", { name: "Завершить", exact: true }).click();
        await clickAndSync(page, "Сохранить и завершить", "/complete");
        await expect(page.getByText("Тренировка завершена")).toBeVisible();
        // Итог: три подхода, первый — с последней правкой (10), ничего не продублировано и не потеряно.
        await expect(page.getByText("Подход 1: 10 повт.")).toBeVisible();
        await expect(page.getByText("Подход 2: 7 повт.")).toBeVisible();
        await expect(page.getByText("Подход 3: 6 повт.")).toBeVisible();
        await expect(page.getByText(/Подход 1: (8|9) повт\./)).toHaveCount(0);

        expect(noWakeLock(consoleErrors)).toEqual([]);
        expect(apiFailures).toEqual([]);
      });
    });
  }
}
