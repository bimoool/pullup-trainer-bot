import { expect, test, type Page } from "@playwright/test";

import { noWakeLock } from "../../fixtures/builderFlow";
import { openJournalEntry, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs, useLiveEngineV1 } from "../../fixtures/setup";
import { pressTelegramBackButton, type TelegramTheme } from "../../fixtures/telegramMock";

// issue #306: сценарий экрана движка v1 (сессии engine_version = 1) — новые старты здесь на v1.
useLiveEngineV1(test);

// Wave 13b review (#293): регрессии навигации/R-4, найденные независимым ревью 43de3b4..6a76084.
// Seeds (scripts/e2e_seed_all.sh): session_recovery 99330{1,2}/99333{1,2} (мутирует), journal_return
// 99331{1,2}/99332{1,2} (только чтение), session_recovery 99334{1,2}/99335{1,2} (запись падает — только чтение); id + retry.
const USERS: Record<number, { drain: number; journal: number; sheet: number; theme: TelegramTheme }> = {
  320: { drain: 993_301, journal: 993_311, sheet: 993_341, theme: "light" },
  390: { drain: 993_331, journal: 993_321, sheet: 993_351, theme: "dark" },
};
const TITLE = "Тренировка восстановления";

const appErrors = (errors: string[]) => noWakeLock(errors).filter((e) => !e.includes("Failed to load resource"));

async function expectNavVisible(page: Page) {
  await expect(page.locator(".bottom-tabbar")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.classList.contains("vp-nav-hidden"))).toBe(false);
}

for (const width of WIDTHS) {
  const { drain, journal, sheet, theme } = USERS[width as 320 | 390];
  test.describe(`Wave 13b review @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: width === 320 ? 640 : 844 } });
    test.setTimeout(120_000);

    test("Журнал → «Открыть тренировку» → «Начать» → назад → назад: снова Журнал, а не Главная", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, journal + testInfo.retry, { theme, backButton: true });
      await openTab(page, "Журнал");
      const monthLabel = page.locator(".journal-month-label");
      const currentMonth = await monthLabel.innerText();
      await page.getByRole("button", { name: "Предыдущий месяц" }).click();
      await expect(monthLabel).not.toHaveText(currentMonth);
      const previousMonth = await monthLabel.innerText();
      await openJournalEntry(page, page.locator(".history-card-clickable").first());
      const open = page.getByTestId("journal-open-workout");
      await open.click();
      await expect(page.getByTestId("workout-detail-title")).toContainText("Возвратная тренировка");

      await page.getByTestId("workout-detail-start").click();
      await expect(page.getByTestId("session-pre")).toBeVisible();
      await pressTelegramBackButton(page);
      await expect(page.getByTestId("workout-detail")).toBeVisible(); // #277: назад — на деталь

      // Деталь открыта из Журнала: её «назад» возвращает в тот же месяц Журнала с той же записью.
      await pressTelegramBackButton(page);
      await expect(page.getByTestId("workout-detail")).toHaveCount(0);
      await expect(open).toBeVisible();
      await pressTelegramBackButton(page);
      await expect(monthLabel).toHaveText(previousMonth);
      await expectNavVisible(page);

      expect(appErrors(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("R-4: «Начать» на Workout Detail при завершении в очереди — сначала досылка, не ложный конфликт", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, drain + testInfo.retry, { theme, allowedApiStatuses: [500] });
      // Первая тренировка из свободного пула «Планов».
      const started = page.waitForResponse((r) => r.url().endsWith("/api/v2/sessions/live") && r.request().method() === "POST");
      await page.getByTestId("my-workout-card").filter({ hasText: TITLE }).click();
      await page.getByRole("button", { name: "Добавить в план" }).click();
      await page.getByRole("button", { name: "Свободный пул" }).click();
      await page.getByRole("button", { name: "Добавить", exact: true }).click();
      const group = page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${TITLE}`) });
      await group.getByRole("button", { name: /^Начать: / }).click();
      await page.getByRole("button", { name: "Начать", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Приготовься", exact: true, level: 2 })).toBeVisible();
      const firstId = ((await (await started).json()) as { id: number }).id;

      // Завершение падает (500) → «Выйти»: завершение лежит в очереди, на сервере сессия ещё STARTED.
      let failing = true;
      await page.route("**/api/v2/sessions/live/*/complete", async (route) => {
        if (failing) {
          await route.fulfill({ status: 500, body: "boom" });
        } else {
          await route.continue();
        }
      });
      await page.getByRole("button", { name: "Завершить", exact: true }).click();
      await page.getByTestId("workout-review").getByRole("button", { name: "Сохранить и завершить" }).click();
      await expect(page.getByTestId("finish-pending")).toHaveAttribute("data-state", "retry");
      await page.getByTestId("finish-leave").click();
      await expectNavVisible(page);
      failing = false;

      // Та же тренировка с Workout Detail (Главная): пред-экран досылает старое завершение,
      // а не предлагает «продолжить» уже завершённую пользователем тренировку.
      const drained = page.waitForResponse((r) => r.url().includes(`/sessions/live/${firstId}/complete`) && r.status() === 200);
      await openTab(page, "Главная");
      await page.getByTestId("my-workout-card").filter({ hasText: TITLE }).click();
      await page.getByTestId("workout-detail-start").click();
      await drained;
      await expect(page.getByTestId("active-session-conflict")).toHaveCount(0);
      const restarted = page.waitForResponse((r) => r.url().endsWith("/api/v2/sessions/live") && r.request().method() === "POST");
      await page.getByRole("button", { name: "Начать", exact: true }).click();
      const second = await restarted;
      expect(second.status()).toBe(200);
      expect(((await second.json()) as { id: number }).id).not.toBe(firstId);
      await expect(page.getByRole("heading", { name: "Приготовься", exact: true, level: 2 })).toBeVisible();

      expect(appErrors(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("«Добавить в план»: пока запрос в полёте, тап по фону не закрывает лист — ошибка не теряется", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, sheet + testInfo.retry, { theme, backButton: true, allowedApiStatuses: [500] });
      await page.getByTestId("my-workout-card").filter({ hasText: TITLE }).click();
      await page.getByRole("button", { name: "Добавить в план" }).click();
      const formSheet = page.getByTestId("form-sheet");
      await expect(formSheet).toBeVisible();
      await page.getByRole("button", { name: "Свободный пул" }).click();

      let release: () => void = () => {};
      const gate = new Promise<void>((resolve) => { release = resolve; });
      await page.route("**/api/v2/plan-items", async (route) => {
        await gate;
        await route.fulfill({ status: 500, body: "boom" });
      });
      await page.getByRole("button", { name: "Добавить", exact: true }).click();
      await page.getByTestId("form-sheet-backdrop").click({ position: { x: 5, y: 5 } });
      await pressTelegramBackButton(page);
      await expect(formSheet).toBeVisible();
      release();
      await expect(formSheet).toContainText("Не удалось добавить");

      // После ответа лист снова закрывается фоном как обычно.
      await page.getByTestId("form-sheet-backdrop").click({ position: { x: 5, y: 5 } });
      await expect(page.getByTestId("workout-detail")).toBeVisible();

      expect(appErrors(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
