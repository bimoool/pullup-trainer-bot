import { expect, test, type Locator, type Page } from "@playwright/test";

import { noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import { isTelegramBackButtonVisible, pressTelegramBackButton } from "../../fixtures/telegramMock";

// #280 — шторка записи Журнала v2 (как в Crimpd: тап по карточке → «Открыть / Изменить / Повторить /
// Удалить»). Действия — те же, что на экране деталей, и по тем же флагам записи.
// Seed: scripts/e2e_seed.py journal_edit — две сегодняшние записи: Builder «Моя силовая» со снимком
// (can_edit, привязана к тренировке → «Открыть тренировку») и историческая «Тренировка» без снимка
// (только «Открыть»); «Бег» (свободная активность) тест создаёт через API. owner_optional_workout —
// факультатив (без «Повторить»: клон бэкенд отклоняет 409). По пользователю на ширину/тему и на retry.
const ACTIONS_USERS = { 320: { id: 998_101, theme: "light" }, 390: { id: 998_111, theme: "dark" } } as const;
// Тест типов создаёт запись «Бег» — свой пользователь, чтобы остальные видели ровно две записи.
const TYPES_USERS = { 320: 998_161, 390: 998_171 } as const;
const DELETE_USERS = { 320: 998_121, 390: 998_131 } as const;
const ELECTIVE_USERS = { 320: 998_141, 390: 998_151 } as const;

type Action = "open" | "edit" | "clone" | "workout" | "delete";
const ALL_ACTIONS: Action[] = ["open", "edit", "clone", "workout", "delete"];

/** Какие из действий шторки сейчас есть на экране (по testid). */
async function sheetActions(page: Page): Promise<Action[]> {
  const present: Action[] = [];
  for (const action of ALL_ACTIONS) {
    if ((await page.getByTestId(`journal-sheet-${action}`).count()) > 0) {
      present.push(action);
    }
  }
  return present;
}

async function expectSheetFits(page: Page, width: number) {
  const box = await page.getByTestId("journal-entry-sheet").boundingBox();
  expect(box, "шторка отрисована").not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(width);
  expect(box!.y).toBeGreaterThanOrEqual(0);
  await expectNoHorizontalOverflow(page, "Журнал: шторка записи");
  for (const button of await page.getByTestId("journal-entry-sheet").getByRole("button").all()) {
    expect((await button.boundingBox())!.height).toBeGreaterThanOrEqual(40);
  }
}

async function createActivity(page: Page) {
  const initData = await page.evaluate(
    () => (window as unknown as { Telegram: { WebApp: { initData: string } } }).Telegram.WebApp.initData,
  );
  const response = await page.request.post("/api/v2/sessions", {
    headers: { "X-Telegram-Init-Data": initData },
    data: {
      source: "freeform", performed_at: new Date(Date.now() - 2 * 60_000).toISOString(), effort: null, comment: null,
      blocks: [], activity_type: "running", duration_seconds: 1800,
    },
  });
  expect(response.ok()).toBe(true);
}

/** Кнопки/ссылки экрана деталей, которые соответствуют действиям шторки. */
async function detailActions(page: Page): Promise<Action[]> {
  const present: Action[] = ["open"];
  const has = async (locator: Locator) => (await locator.count()) > 0;
  if (await has(page.getByRole("button", { name: /Изменить/ }))) present.push("edit");
  if (await has(page.getByRole("button", { name: /Повторить/ }))) present.push("clone");
  if (await has(page.getByTestId("journal-open-workout"))) present.push("workout");
  if (await has(page.getByRole("button", { name: /Удалить/ }))) present.push("delete");
  return present;
}

for (const width of WIDTHS) {
  const { id, theme } = ACTIONS_USERS[width as 320 | 390];
  test.describe(`Journal entry sheet @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 760 } });
    test.setTimeout(90_000);

    test("действия по типам записей совпадают с экраном деталей; «Открыть» ведёт на деталь", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, TYPES_USERS[width as 320 | 390] + testInfo.retry, { theme, backButton: true });
      await createActivity(page);
      await openTab(page, "Журнал");
      const cards = page.locator(".history-card-clickable");
      await expect(cards).toHaveCount(3);
      const builder = cards.filter({ hasText: "Моя силовая" });
      const historical = cards.filter({ hasText: "Тренировка" }).filter({ hasNotText: "Моя силовая" });
      const activity = cards.filter({ hasText: "Бег" });

      const expected: [string, Locator, Action[]][] = [
        ["Builder-запись", builder, ["open", "edit", "clone", "workout", "delete"]],
        ["историческая без снимка", historical, ["open"]],
        ["свободная активность", activity, ["open", "edit", "clone", "delete"]],
      ];
      for (const [label, card, actions] of expected) {
        await card.click();
        const sheet = page.getByTestId("journal-entry-sheet");
        await expect(sheet, label).toBeVisible();
        await expect(sheet).toHaveAttribute("role", "dialog");
        await expect(sheet).toHaveAttribute("aria-modal", "true");
        expect(await sheetActions(page), label).toEqual(actions);
        await expect(page.getByTestId("journal-sheet-cancel")).toHaveText("Отмена");
        await expectSheetFits(page, width);
        await page.getByTestId("journal-sheet-open").click();
        // «Открыть» — прежний экран деталей, и его кнопки — ровно те же действия.
        await expect(sheet).toHaveCount(0);
        await expect(page.getByRole("button", { name: "← Назад" })).toBeVisible();
        expect(await detailActions(page), `${label}: деталь`).toEqual(actions);
        await page.getByRole("button", { name: "← Назад" }).click();
        await expect(cards).toHaveCount(3);
      }

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("закрытие: Escape, фон, «Отмена», Telegram BackButton; фокус внутри шторки и возвращается на карточку", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, id + testInfo.retry, { theme, backButton: true });
      await openTab(page, "Журнал");
      const cards = page.locator(".history-card-clickable");
      await expect(cards).toHaveCount(2);
      const card = cards.filter({ hasText: "Моя силовая" });
      const sheet = page.getByTestId("journal-entry-sheet");

      const closers: [string, () => Promise<void>][] = [
        ["Escape", () => page.keyboard.press("Escape")],
        ["фон", () => page.getByTestId("journal-entry-sheet-backdrop").click({ position: { x: 6, y: 6 } })],
        ["«Отмена»", () => page.getByTestId("journal-sheet-cancel").click()],
        ["Telegram BackButton", () => pressTelegramBackButton(page)],
      ];
      for (const [name, close] of closers) {
        await card.click();
        await expect(sheet, name).toBeVisible();
        // Фокус ушёл в саму шторку (не на первое действие — зажатый Enter не нажмёт «Открыть»), Tab его не выпускает.
        await expect(sheet, name).toBeFocused();
        await page.keyboard.press("Tab");
        await expect(page.getByTestId("journal-sheet-open"), name).toBeFocused();
        for (let step = 0; step < 8; step++) {
          await page.keyboard.press("Tab");
          expect(await page.evaluate(() => document.activeElement?.closest('[data-testid="journal-entry-sheet"]') !== null), name).toBe(true);
        }
        await page.keyboard.press("Shift+Tab");
        expect(await page.evaluate(() => document.activeElement?.closest('[data-testid="journal-entry-sheet"]') !== null), name).toBe(true);
        expect(await isTelegramBackButtonVisible(page), `${name}: BackButton виден`).toBe(true);

        await close();
        await expect(sheet, name).toHaveCount(0);
        await expect(card, `${name}: фокус вернулся на карточку`).toBeFocused();
        await expect(cards, name).toHaveCount(2); // ничего не открылось и не удалилось
        await expect(page.getByRole("button", { name: "← Назад" }), name).toHaveCount(0);
        expect(await isTelegramBackButtonVisible(page), `${name}: BackButton скрыт`).toBe(false);
      }

      // Клавиатура: Enter на карточке открывает шторку, Enter на «Открыть» — деталь.
      await card.focus();
      await page.keyboard.press("Enter");
      await expect(sheet).toBeVisible();
      await expect(sheet).toBeFocused();
      await page.keyboard.press("Enter"); // повторный/зажатый Enter по шторке ничего не активирует
      await expect(sheet).toBeVisible();
      await page.keyboard.press("Tab");
      await page.keyboard.press("Enter");
      await expect(page.getByRole("button", { name: /Удалить/ })).toBeVisible();
      await pressTelegramBackButton(page);
      await expect(cards).toHaveCount(2);

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("«Изменить» и «Повторить» из шторки открывают форму сразу; «Отмена» ведёт в Журнал, не в тупик", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, id + testInfo.retry, { theme, backButton: true });
      await openTab(page, "Журнал");
      const cards = page.locator(".history-card-clickable");
      await expect(cards).toHaveCount(2);
      const card = cards.filter({ hasText: "Моя силовая" });

      await card.click();
      await page.getByTestId("journal-sheet-edit").click();
      await expect(page.getByTestId("journal-entry-sheet")).toHaveCount(0);
      const form = page.getByTestId("journal-edit-form");
      await expect(form).toBeVisible();
      await expect(form.getByLabel("Подход 1: значение")).toHaveValue("8");
      await expectNoHorizontalOverflow(page, "Журнал: форма правки из шторки");
      await form.getByRole("button", { name: "Отмена" }).click();
      await expect(form).toHaveCount(0);
      await expect(cards).toHaveCount(2);

      await card.click();
      await page.getByTestId("journal-sheet-clone").click();
      const clone = page.getByTestId("journal-clone-form");
      await expect(clone).toBeVisible();
      await expectNoHorizontalOverflow(page, "Журнал: форма клона из шторки");
      await pressTelegramBackButton(page); // BackButton — тот же выход, что «Отмена»
      await expect(clone).toHaveCount(0);
      await expect(cards).toHaveCount(2);

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });

  test.describe(`Journal entry sheet: delete @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 760 } });
    test.setTimeout(90_000);

    test("удаление: «Отмена» подтверждения ничего не удаляет; подтверждённое — убирает запись и закрывает шторку", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, DELETE_USERS[width as 320 | 390] + testInfo.retry, { theme, backButton: true });
      await openTab(page, "Журнал");
      const cards = page.locator(".history-card-clickable");
      await expect(cards).toHaveCount(2);
      const card = cards.filter({ hasText: "Моя силовая" });
      const deletes: string[] = [];
      page.on("request", (request) => {
        if (request.method() === "DELETE" && request.url().includes("/api/v2/sessions/")) {
          deletes.push(request.url());
        }
      });

      // Подтверждение отклонено: запроса нет, шторка остаётся.
      let confirmText = "";
      page.once("dialog", (dialog) => { confirmText = dialog.message(); void dialog.dismiss(); });
      await card.click();
      await page.getByTestId("journal-sheet-delete").click();
      await expect.poll(() => confirmText).toContain("Отменить это будет нельзя");
      await expect(page.getByTestId("journal-entry-sheet")).toBeVisible();
      expect(deletes).toHaveLength(0);
      await expect(cards).toHaveCount(2);

      // Подтверждено (двойной клик — один DELETE): запись исчезла, шторки нет, соседняя запись цела.
      page.on("dialog", (dialog) => void dialog.accept());
      await page.route("**/api/v2/sessions/*", async (route) => {
        if (route.request().method() === "DELETE") {
          await new Promise((resolve) => setTimeout(resolve, 700)); // окно, в котором кнопки заблокированы
        }
        await route.continue();
      });
      const deleted = page.waitForResponse((r) => r.request().method() === "DELETE" && r.url().includes("/api/v2/sessions/"));
      await page.getByTestId("journal-sheet-delete").dblclick();
      // Пока идёт удаление, фокус не падает на страницу под шторкой, Tab его не выпускает (aria-modal).
      await expect(page.getByTestId("journal-entry-sheet")).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(page.getByTestId("journal-entry-sheet")).toBeFocused();
      expect((await deleted).status()).toBe(204);
      await expect(page.getByTestId("journal-entry-sheet")).toHaveCount(0);
      await expect(cards).toHaveCount(1);
      await expect(card).toHaveCount(0);
      expect(deletes).toHaveLength(1);
      await expectNoHorizontalOverflow(page, "Журнал: после удаления из шторки");

      // Оставшаяся (историческая) запись: удалить нельзя — в шторке только «Открыть».
      await cards.first().click();
      expect(await sheetActions(page)).toEqual(["open"]);
      await page.getByTestId("journal-sheet-cancel").click();

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });

  test.describe(`Journal entry sheet: elective @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 760 } });
    test.setTimeout(90_000);

    test("факультатив: «Изменить» и «Удалить» есть, «Повторить» нет (клон — 409)", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, ELECTIVE_USERS[width as 320 | 390] + testInfo.retry, { theme, backButton: true });
      await openTab(page, "Журнал");
      const cards = page.locator(".history-card-clickable");
      await expect(cards).toHaveCount(2);
      await cards.filter({ hasText: "Факультатив — 3 минуты подтягиваний" }).click();
      await expect(page.getByTestId("journal-entry-sheet")).toBeVisible();
      expect(await sheetActions(page)).toEqual(["open", "edit", "delete"]);
      await expectSheetFits(page, width);
      await page.getByTestId("journal-sheet-cancel").click();

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
