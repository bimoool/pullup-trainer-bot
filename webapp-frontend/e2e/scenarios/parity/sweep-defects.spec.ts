import { expect, test, type Page } from "@playwright/test";

import { noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import { isTelegramBackButtonVisible, pressTelegramBackButton } from "../../fixtures/telegramMock";

// #277 «Full sweep» — регрессии трёх найденных дефектов:
//   D1 «Записать» с Workout Detail → «← Назад» / Telegram BackButton возвращают на деталь (не в Журнал);
//   D2 Профиль считает тренировки Журнала v2 (а не «Тренировок пока не было.»);
//   D3 Планы без курсов: подсказка «Добавьте курс на Главной» с кнопкой-переходом на Главную.
// Seed: scripts/e2e_seed.py sweep_defects — «Золотая тренировка», план без курсов, 2 завершённые
// v2-сессии (2 и 5 дней назад), ни одной legacy-тренировки. Пользователь = база + 2 * индекс теста + retry.
const USERS = { 320: { base: 997_501, theme: "light" }, 390: { base: 997_521, theme: "dark" } } as const;
const WORKOUT = "Золотая тренировка";
const BACKDATED_BADGE = "Записана задним числом";
// В сиде sweep_defects уже ДВЕ BACKDATED-сессии (2 и 5 дней назад) — сценарий добавляет третью, поэтому общий бейдж
// «задним числом» её не идентифицирует. Исходные записи не удаляем: считаем их и ищем новую по дню и содержимому.
const SEED_BACKDATED = 2;
const USER_TIME_ZONE = "Europe/Moscow"; // профиль пользователя sweep_defects (_QUESTIONNAIRE_DEFAULTS)

const backdatedCards = (page: Page) =>
  page.getByTestId("journal-card").filter({ has: page.getByTestId("journal-kind-badge").filter({ hasText: BACKDATED_BADGE }) });
// День Журнала в поясе профиля (YYYY-MM-DD), как у data-date группы дня: запись «сегодня» — performed_at «сейчас».
const todayInUserZone = (page: Page) =>
  page.evaluate((tz) => new Intl.DateTimeFormat("en-CA", { timeZone: tz }).format(new Date()), USER_TIME_ZONE);

async function openDetailFromHome(page: Page) {
  await page.getByTestId("my-workout-card").filter({ hasText: WORKOUT }).click();
  await expect(page.getByTestId("workout-detail")).toBeVisible();
}

async function expectBackOnDetail(page: Page) {
  await expect(page.getByTestId("workout-detail")).toBeVisible();
  await expect(page.getByTestId("journal-log-form")).toHaveCount(0);
  await expect(page.getByTestId("workout-detail-log")).toBeVisible();
}

for (const width of WIDTHS) {
  const { base, theme } = USERS[width as 320 | 390];
  test.describe(`Sweep defects @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 800 } });
    test.setTimeout(90_000);

    test("D1: «Записать» → «← Назад» возвращает на Workout Detail (Главная)", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, base + testInfo.retry, { theme, backButton: true });
      await openDetailFromHome(page);
      await page.getByTestId("workout-detail-log").click();
      await expect(page.getByTestId("journal-log-form")).toBeVisible();
      await expectNoHorizontalOverflow(page, "форма «Записать»");

      await page.getByRole("button", { name: "← Назад" }).click();
      await expectBackOnDetail(page);
      await expectNoHorizontalOverflow(page, "Workout Detail после «← Назад»");

      // У детали нет экранной кнопки — закрывает Telegram BackButton: после возврата на саму Главную (не в Журнал).
      await pressTelegramBackButton(page);
      await expect(page.getByTestId("my-workout-card").filter({ hasText: WORKOUT })).toBeVisible();

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("D1: Telegram BackButton из формы «Записать» возвращает на Workout Detail", async ({ page }, testInfo) => {
      await openAppAs(page, base + 2 + testInfo.retry, { theme, backButton: true });
      await openDetailFromHome(page);
      await page.getByTestId("workout-detail-log").click();
      await expect(page.getByTestId("journal-log-form")).toBeVisible();
      expect(await isTelegramBackButtonVisible(page), "Telegram BackButton в форме").toBe(true);

      await pressTelegramBackButton(page);
      await expectBackOnDetail(page);
    });

    test("D1: «Записать» с детали на вкладке «Планы» → «← Назад» возвращает на деталь в «Планах»", async ({ page }, testInfo) => {
      await openAppAs(page, base + 4 + testInfo.retry, { theme, backButton: true });
      await openTab(page, "Планы");
      await page.getByRole("button", { name: "Мои тренировки" }).click();
      await page.getByText(WORKOUT, { exact: true }).first().click();
      await expect(page.getByTestId("workout-detail")).toBeVisible();
      await page.getByTestId("workout-detail-log").click();
      await expect(page.getByTestId("journal-log-form")).toBeVisible();

      await page.getByRole("button", { name: "← Назад" }).click();
      await expectBackOnDetail(page);
      // Из детали — в список «Мои тренировки» (как и раньше), вкладка осталась «Планы».
      await pressTelegramBackButton(page);
      await expect(page.getByText("Мои тренировки", { exact: true })).toBeVisible();
    });

    test("D1: после «← Назад» повторное «Записать» и сохранение — ровно одна новая запись в Журнале", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, base + 6 + testInfo.retry, { theme });
      // Исходное состояние: только две сидовые BACKDATED-записи, новой ещё нет.
      await openTab(page, "Журнал");
      await expect(backdatedCards(page)).toHaveCount(SEED_BACKDATED);
      await openTab(page, "Главная");

      await openDetailFromHome(page);
      await page.getByTestId("workout-detail-log").click();
      await page.getByRole("button", { name: "← Назад" }).click();
      await expectBackOnDetail(page);

      await page.getByTestId("workout-detail-log").click();
      await expect(page.getByTestId("log-workout-select").locator("option:checked")).toHaveText(WORKOUT);
      const setInputs = page.locator('[data-testid^="log-set-"]');
      await setInputs.nth(0).fill("8");
      await setInputs.nth(1).fill("6");
      await page.getByTestId("log-save").click();

      // После сохранения — Журнал (не деталь): ровно одна новая BACKDATED-запись, без дублирования.
      await expect(page.getByTestId("workout-detail")).toHaveCount(0);
      await expect(backdatedCards(page)).toHaveCount(SEED_BACKDATED + 1);

      // Новая запись — единственная в сегодняшнем дне (сид: 2 и 5 дней назад), и именно её содержание проверяем.
      const today = await todayInUserZone(page);
      const created = page.locator(`.journal-day[data-date="${today}"]`).getByTestId("journal-card");
      await expect(created).toHaveCount(1);
      await expect(created.getByTestId("journal-kind-badge")).toHaveText(BACKDATED_BADGE);
      await expect(created.locator(".journal-card-name")).toHaveText(WORKOUT);
      // карточка — суммы (#286): 2 подхода, 14 повторов (у сидовых записей 15); факт «8 · 6» — в деталях записи
      await expect(created.locator('.journal-stat[data-stat="sets"] .journal-stat-value')).toHaveText("2");
      await expect(created.locator('.journal-stat[data-stat="reps"] .journal-stat-value')).toHaveText("14");

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("D2: Профиль учитывает завершённые тренировки Журнала v2", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, base + 8 + testInfo.retry, { theme });
      await openTab(page, "Профиль");
      await expect(page.getByText("Личные данные")).toBeVisible();

      await expect(page.getByText("Тренировок пока не было.")).toHaveCount(0);
      await expect(page.getByText("Последняя тренировка: 2 дня назад.")).toBeVisible();
      await expect(page.locator(".stat-tile").filter({ hasText: /Тренировк/u })).toContainText("2");
      await expectNoHorizontalOverflow(page, "Профиль");

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("D3: Планы без курсов — кнопка «Выбрать курс на Главной» ведёт на Главную", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, base + 8 + testInfo.retry, { theme });
      await openTab(page, "Планы");
      await expect(page.getByTestId("plans-now-empty")).toContainText("Добавьте курс на Главной");
      const open = page.getByTestId("plans-now-card").getByRole("button", { name: "Выбрать курс на Главной" });
      await expect(open).toBeVisible();
      await expectNoHorizontalOverflow(page, "Планы без курсов");

      await open.click();
      await expect(page.getByTestId("home-header")).toBeVisible();
      await expect(page.getByTestId("plans-now-card")).toHaveCount(0);

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
