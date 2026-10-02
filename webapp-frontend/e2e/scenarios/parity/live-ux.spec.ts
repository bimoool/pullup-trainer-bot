import { expect, test, type Locator, type Page } from "@playwright/test";

import { clickAndSync, noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import type { TelegramTheme } from "../../fixtures/telegramMock";

// Live Session UX fixes (#285 A): M1 — экранная клавиатура vs липкий транспорт и Enter в поле
// записи подхода. Клавиатура = уменьшение высоты окна (как в Telegram WebView, см.
// keyboard-viewport.spec.ts). Seed: session_recovery — Workout «Тренировка восстановления»,
// reps 3 x 8, отдых 60 с; 9978xx — по пользователю на ширину × тему, на тест id + 2*индекс + retry.
const TITLE = "Тренировка восстановления";
const BASE: Record<number, Record<TelegramTheme, number>> = {
  320: { light: 997_801, dark: 997_811 },
  390: { light: 997_821, dark: 997_831 },
};
const KEYBOARD_VH = 380;
const VALUE_FIELD = /Результат|Секунды|Повторений/;

/** Старт из свободного пула «Планов» до «Приготовься». */
async function startLive(page: Page) {
  await page.getByTestId("my-workout-card").filter({ hasText: TITLE }).click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await page.getByRole("button", { name: "Свободный пул" }).click();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  const group = page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${TITLE}`) });
  await group.getByRole("button", { name: "Начать", exact: true }).click();
  await page.getByRole("button", { name: "Начать", exact: true }).click(); // SessionPreScreen
  await expect(page.getByRole("heading", { name: "Приготовься", exact: true, level: 2 })).toBeVisible();
}

async function startToGo(page: Page) {
  await startLive(page);
  await clickAndSync(page, "Готов", "/phase/next");
  await expect(page.getByRole("heading", { name: "Пошёл", exact: true, level: 2 })).toBeVisible();
}

async function boxOf(locator: Locator, what: string) {
  const box = await locator.boundingBox();
  expect(box, `${what}: нет геометрии`).not.toBeNull();
  return box!;
}

/** Элемент виден в окне и не перекрыт ничем (центр по elementFromPoint), без доп. прокрутки. */
async function expectVisibleUncovered(page: Page, target: Locator, what: string) {
  const box = await boxOf(target, what);
  const vh = page.viewportSize()!.height;
  expect(box.y, `${what}: выше окна`).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height, `${what}: ниже окна`).toBeLessThanOrEqual(vh);
  const hit = await target.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return top === el || el.contains(top);
  });
  expect(hit, `${what}: перекрыт другим элементом`).toBe(true);
}

for (const width of WIDTHS) {
  for (const theme of ["light", "dark"] as TelegramTheme[]) {
    test.describe(`Live UX #285 @${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: width === 320 ? 640 : 844 } });
      test.setTimeout(120_000);

      const userFor = (index: number, retry: number) => BASE[width][theme] + 2 * index + retry;

      test("M1: поле записи при клавиатуре не закрыто транспортом, Enter записывает подход", async ({ page }, testInfo) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, userFor(0, testInfo.retry), { theme });
        await startToGo(page);
        const { height: fullHeight } = page.viewportSize()!;
        const input = page.getByLabel(VALUE_FIELD);
        const done = page.getByRole("button", { name: "Готово", exact: true });
        const transport = page.locator(".live-transport");

        // Клавиатура открылась: поле сфокусировано, окно стало ниже; браузер минимально прокручивает
        // сфокусированное поле к видимой области с учётом scroll-padding (block: "nearest" — тот же
        // алгоритм), т.е. поле оказывается у нижнего края окна — там, где был бы липкий транспорт.
        await input.focus();
        await page.setViewportSize({ width, height: KEYBOARD_VH });
        await page.evaluate(() => window.scrollTo(0, 0));
        await input.evaluate((el) => el.scrollIntoView({ block: "nearest" }));
        await expect(page.locator(".live-screen")).toHaveAttribute("data-field-focus", "true");

        await expectVisibleUncovered(page, input, "поле результата");
        const inputBox = await boxOf(input, "поле результата");
        const transportBox = await boxOf(transport, "транспорт");
        expect(
          inputBox.y + inputBox.height,
          "транспорт перекрывает поле (пересечение боксов)",
        ).toBeLessThanOrEqual(transportBox.y + 1);
        // «Готово» достижимо прокруткой и не перекрыто.
        await done.scrollIntoViewIfNeeded();
        await expectVisibleUncovered(page, done, "«Готово»");
        await expectNoHorizontalOverflow(page, "Live: поле записи с клавиатурой");
        await expect(transport).toHaveCSS("position", "static");

        // Enter/«Go» в поле — тот же защищённый обработчик, что у «Готово»: ровно один подход.
        await input.focus();
        await input.fill("8");
        const batches: string[] = [];
        page.on("request", (request) => {
          if (request.method() === "POST" && request.url().includes("/sets:batch")) {
            batches.push(request.url());
          }
        });
        const sync = page.waitForResponse((r) => r.url().includes("/sets:batch") && r.status() === 200);
        await page.keyboard.press("Enter");
        await page.keyboard.press("Enter"); // двойной Enter не создаёт второй подход
        await sync;
        await expect(page.getByRole("heading", { name: "Отдых", exact: true, level: 2 })).toBeVisible();
        expect(batches).toHaveLength(1);

        // Клавиатура закрыта: транспорт снова липнет к низу окна.
        await page.setViewportSize({ width, height: fullHeight });
        await expect(page.locator(".live-screen")).not.toHaveAttribute("data-field-focus", "true");
        await expect(transport).toHaveCSS("position", "sticky");

        // Enter в пустом поле ничего не записывает.
        await clickAndSync(page, "Пропустить отдых", "/phase/next");
        await clickAndSync(page, "Готов", "/phase/next");
        await expect(input).toHaveValue("");
        await input.focus();
        await input.press("Enter");
        await page.waitForTimeout(400);
        expect(batches).toHaveLength(1);
        await expect(page.getByRole("heading", { name: "Пошёл", exact: true, level: 2 })).toBeVisible();

        expect(noWakeLock(consoleErrors)).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

    });
  }
}
