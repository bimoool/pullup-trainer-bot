import { expect, test, type Page } from "@playwright/test";

import { clickAndSync, noWakeLock, playSets, startWorkout } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import { pressTelegramBackButton, type TelegramTheme } from "../../fixtures/telegramMock";

// #287 — завершение живой тренировки в очереди (HIGH 1/2) и фокус поля (MED 3).
// HIGH 1: завершение, поставленное офлайн, не застревает: досылается на mount после повторного
// открытия, повтор виден всегда (онлайн, флаш не идёт), Back уводит с экрана, потерянный ответ
// complete (сессия уже завершена, переход из очереди → 404) считается успехом.
// HIGH 2: на interstitial между блоками с завершением в очереди нет «Начать».
// Seeds (scripts/e2e_seed_all.sh): session_recovery 9979{01,11}+0..7 — «Тренировка восстановления»
// (reps 3 x 8, отдых 60 с), на тест id + 2*индекс + retry; builder_workouts 9979{51,61} (+retry) — «Дубли»
// (reps 2 x 8 → time → max, ручные переходы).
const TITLE = "Тренировка восстановления";
const USERS: Record<number, { base: number; builder: number; theme: TelegramTheme }> = {
  320: { base: 997_901, builder: 997_951, theme: "light" },
  390: { base: 997_911, builder: 997_961, theme: "dark" },
};
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

/** «Завершить» → review (оценка 3, заметка) → «Сохранить и завершить» без сети: завершение в очереди. */
async function queueFinishOffline(page: Page, context: import("@playwright/test").BrowserContext, comment: string) {
  await page.getByRole("button", { name: "Завершить", exact: true }).click();
  const review = page.getByTestId("workout-review");
  await expect(review).toBeVisible();
  await review.getByTestId("workout-effort").getByRole("button").nth(2).click();
  await review.getByRole("textbox", { name: "Заметка к тренировке" }).fill(comment);
  await context.setOffline(true);
  await review.getByRole("button", { name: "Сохранить и завершить" }).click();
  await expect(review).toHaveCount(0);
  const status = page.getByTestId("finish-pending");
  await expect(status).toHaveAttribute("data-state", "offline");
  await expect(status).toContainText("отправится, когда появится сеть");
  return status;
}

function trackCompletes(page: Page): string[] {
  const bodies: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && /\/sessions\/live\/\d+\/complete$/.test(new URL(request.url()).pathname)) {
      bodies.push(request.postData() ?? "");
    }
  });
  return bodies;
}

const completeOk = (page: Page) =>
  page.waitForResponse((r) => /\/sessions\/live\/\d+\/complete$/.test(new URL(r.url()).pathname) && r.status() === 200);

/** Ожидаемые 4xx/5xx в консоли Chromium («Failed to load resource») — шум намеренных ответов. */
const appErrors = (errors: string[]) => noWakeLock(errors).filter((e) => !e.includes("Failed to load resource"));

for (const width of WIDTHS) {
  const { base, builder, theme } = USERS[width];
  test.describe(`Live finish-pending #287 @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: width === 320 ? 640 : 844 } });
    test.setTimeout(120_000);
    const userFor = (index: number, retry: number) => base + 2 * index + retry;

    test("HIGH 1: офлайн-завершение → приложение закрыто без сети → открыто онлайн: завершение уходит само", async ({ page, context }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, userFor(0, testInfo.retry), { theme });
      await startLive(page);
      const completes = trackCompletes(page);
      await queueFinishOffline(page, context, "закрыл без сети");
      await expectNoHorizontalOverflow(page, "Live: завершение в очереди");
      expect(completes).toEqual([]);

      // Mini App закрыт, пока сети нет: этот экземпляр события `online` уже не увидит. Открыт снова —
      // уже онлайн: App возобновляет сессию, экран досылает завершение на mount (раньше — вечное
      // «Завершаю тренировку…» без действий).
      await page.goto("about:blank");
      await context.setOffline(false);
      const complete = completeOk(page);
      await page.goto("/");
      await complete;
      await expect(page.getByText("Тренировка завершена")).toBeVisible();
      expect(completes).toHaveLength(1);
      expect(JSON.parse(completes[0])).toMatchObject({ effort: "3", comment: "закрыл без сети" });

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("HIGH 1: Back при завершении в очереди уводит к вкладкам; сеть вернулась — завершение досылается без экрана", async ({ page, context }, testInfo) => {
      const dialogs: string[] = [];
      page.on("dialog", (dialog) => {
        dialogs.push(dialog.message());
        void dialog.dismiss();
      });
      const { consoleErrors, apiFailures } = await openAppAs(page, userFor(1, testInfo.retry), { theme, backButton: true });
      await startLive(page);
      const completes = trackCompletes(page);
      await queueFinishOffline(page, context, "ушёл назад");
      await expect(page.getByTestId("finish-leave")).toBeVisible();

      // Back не игнорируется: экран закрыт, данные остались в IndexedDB, confirm не показан.
      await pressTelegramBackButton(page);
      await expect(page.locator(".bottom-tabbar")).toBeVisible();
      await expect(page.getByTestId("finish-pending")).toHaveCount(0);
      expect(dialogs).toEqual([]);
      expect(completes).toEqual([]);

      // Сеть вернулась, пока открыты вкладки: завершение из очереди досылает App (событие `online`),
      // с оценкой и заметкой; повторное открытие уже не находит активной сессии и снимка.
      const complete = completeOk(page);
      await context.setOffline(false);
      await complete;
      expect(completes).toHaveLength(1);
      expect(JSON.parse(completes[0])).toMatchObject({ effort: "3", comment: "ушёл назад" });
      await page.reload();
      await expect(page.locator(".bottom-tabbar")).toBeVisible();
      await expect(page.getByText("Живая тренировка")).toHaveCount(0);
      expect(await page.evaluate(() => new Promise((resolve) => {
        const open = indexedDB.open("keyval-store");
        open.onsuccess = () => {
          const read = open.result.transaction("keyval").objectStore("keyval").get("pullup:v2:live-session");
          read.onsuccess = () => resolve(read.result ?? null);
        };
      }))).toBeNull();
      expect(completes).toHaveLength(1);

      // Вкладки, открытые без сети, не загрузили данные — «Failed to load resource» ожидаем.
      expect(appErrors(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("HIGH 1: ответ complete потерян → «Отправить ещё раз» → 404 на переходе из очереди → сессия уже завершена → Summary", async ({ page, context }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, userFor(2, testInfo.retry), { theme, allowedApiStatuses: [404, 500] });
      await startLive(page);
      const completes = trackCompletes(page);

      // Без сети: «Готов» (переход фазы в очереди), затем завершение.
      await context.setOffline(true);
      await page.getByRole("button", { name: "Готов", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Пошёл", exact: true, level: 2 })).toBeVisible();
      await queueFinishOffline(page, context, "ответ потерян");

      // Сеть вернулась: переход и complete дошли до сервера, но ответ complete потерян (500 клиенту).
      let lose = true;
      await page.route("**/api/v2/sessions/live/*/complete", async (route) => {
        if (lose) {
          lose = false;
          await route.fetch();
          await route.fulfill({ status: 500, body: "lost" });
        } else {
          await route.continue();
        }
      });
      const lost = page.waitForResponse((r) => r.url().endsWith("/complete") && r.status() === 500);
      await context.setOffline(false);
      await lost;
      const status = page.getByTestId("finish-pending");
      await expect(status).toHaveAttribute("data-state", "retry");
      await expect(status).toContainText("Не удалось отправить завершение");
      const retry = page.getByTestId("finish-retry");
      await expect(retry).toBeVisible();
      await expectNoHorizontalOverflow(page, "Live: повтор завершения");

      // Повтор: переход из очереди получает 404 (сессия уже не идёт) — это не тупик: сессия больше не
      // активна, идемпотентный complete возвращает её итог.
      const notFound = page.waitForResponse((r) => r.url().includes("/phase/next") && r.status() === 404);
      const complete = completeOk(page);
      await retry.click();
      await notFound;
      await complete;
      await expect(page.getByText("Тренировка завершена")).toBeVisible();
      expect(completes).toHaveLength(2); // потерянный + повтор; прогрессия сервером применена один раз

      expect(appErrors(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("MED 3: фокус остаётся в поле (iOS: тап по кнопке без blur) — транспорт не прилипает под клавиатуру", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, userFor(3, testInfo.retry), { theme });
      await startLive(page);
      await clickAndSync(page, "Готов", "/phase/next");
      const input = page.getByLabel(VALUE_FIELD);
      const screen = page.locator(".live-screen");
      const transport = page.locator(".live-transport");
      await input.focus();
      await expect(screen).toHaveAttribute("data-field-focus", "true");

      // Safari не фокусирует кнопки по тапу: pointerdown/pointerup на неактивном «Готово» без blur
      // поля — клавиатура остаётся, транспорт должен оставаться «отлипшим».
      await page.getByRole("button", { name: "Готово", exact: true }).evaluate((button) => {
        for (const type of ["pointerdown", "pointerup"]) {
          button.dispatchEvent(new PointerEvent(type, { bubbles: true, cancelable: true, pointerType: "touch" }));
        }
      });
      // Скролл-драг, начатый на транспорте (pointercancel вместо pointerup), — то же самое.
      await transport.evaluate((bar) => {
        bar.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, pointerType: "touch" }));
        bar.dispatchEvent(new PointerEvent("pointercancel", { bubbles: true, pointerType: "touch" }));
      });
      await page.waitForTimeout(1_000); // > FIELD_BLUR_GRACE_MS × 2: и таймер, и опрос успели бы снять
      await expect(input).toBeFocused();
      await expect(screen).toHaveAttribute("data-field-focus", "true");
      await expect(transport).toHaveCSS("position", "static");

      // Поле действительно потеряло фокус — транспорт возвращается к низу окна.
      await input.blur();
      await expect(screen).not.toHaveAttribute("data-field-focus", "true");
      await expect(transport).toHaveCSS("position", "sticky");

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("HIGH 2: interstitial между блоками с завершением в очереди — без «Начать», завершение уходит", async ({ page, context }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, builder + testInfo.retry, { theme });
      const blockStarts: string[] = [];
      page.on("request", (request) => {
        if (request.url().includes("/blocks/start")) {
          blockStarts.push(request.url());
        }
      });
      await startWorkout(page, "Дубли");
      await playSets(page, ["8", "8"]);
      await expect(page.getByText("Следующее упражнение")).toBeVisible();
      await expect(page.getByRole("button", { name: "Начать", exact: true })).toBeVisible();

      const completes = trackCompletes(page);
      await queueFinishOffline(page, context, "между блоками");
      // «Начать» стартовало бы блок и стёрло снимок вместе с завершением и оценкой.
      await expect(page.getByRole("button", { name: "Начать", exact: true })).toHaveCount(0);
      await expect(page.getByText("Следующее упражнение")).toHaveCount(0);
      await expect(page.getByTestId("extra-set-button")).toHaveCount(0);
      await expectNoHorizontalOverflow(page, "Live: interstitial, завершение в очереди");

      const complete = completeOk(page);
      await context.setOffline(false);
      await complete;
      await expect(page.getByText("Тренировка завершена")).toBeVisible();
      expect(completes).toHaveLength(1);
      expect(JSON.parse(completes[0])).toMatchObject({ effort: "3", comment: "между блоками" });
      expect(blockStarts).toEqual([]);

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
