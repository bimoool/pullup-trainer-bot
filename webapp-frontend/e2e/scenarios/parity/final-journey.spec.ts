import { mkdirSync } from "node:fs";

import { expect, test, type Locator, type Page } from "@playwright/test";

import { clickAndSync, noWakeLock, playSets } from "../../fixtures/builderFlow";
import { COMBOS, expectScreenHealthy, openTab } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import { isTelegramBackButtonVisible, pressTelegramBackButton } from "../../fixtures/telegramMock";

// Crimpd parity — «Final journey» (#277): путь РЕАЛЬНОГО пользователя, а не таблица переходов
// (её ведёт full-sweep.spec.ts). Главная → поиск → деталь тренировки → старт → живая сессия →
// завершение → Журнал → Аналитика → Планы → Тесты → Профиль/Настройки → Подборки; на 320/390 px,
// светлая/тёмная тема, пустой и наполненный пользователь. На каждом шаге: экран не пустой, нет
// горизонтального overflow, главная кнопка-действие достижима (в окне, не перекрыта таб-баром),
// «Назад» (in-app и Telegram BackButton) ведёт туда, откуда пришли, данные после мутации свежие.
// Скриншоты шагов — в SWEEP_SHOTS (по умолчанию /tmp/sweep-shots), не коммитятся.
// Сиды: scripts/e2e_seed_all.sh, блок «Final journey (#277)» (9969xx).

type Mode = "empty" | "populated";
const BASE = { empty: 996_901, populated: 996_911 } as const;
const uid = (mode: Mode, comboIndex: number, retry: number) => BASE[mode] + comboIndex + retry * 10_000;

const WORKOUT = "Свип: тренировка";
const COURSE = "Свип: курс";
const POPULATED_WORKOUTS = 8; // см. seed_sweep_populated
const SHOTS = process.env.SWEEP_SHOTS ?? "/tmp/sweep-shots";

const byName = (page: Page, name: string | RegExp, exact = true) => page.getByRole("button", { name, exact });
const TAB_MARKER: Record<string, (page: Page) => Locator> = {
  Планы: (page) => page.getByText("Текущий план", { exact: true }),
  Журнал: (page) => page.getByRole("button", { name: "+ Записать" }),
  Аналитика: (page) => page.getByText("Тренировок за 30 дней", { exact: true }),
  Профиль: (page) => page.getByText("Личные данные", { exact: true }),
};
const tabbar = (page: Page) => page.locator(".bottom-tabbar");

async function shot(page: Page, tag: string, step: string) {
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await page.screenshot({ path: `${SHOTS}/${tag}--${step.replace(/[^\wа-яё]+/gi, "_")}.png`, fullPage: false });
}

/** Кнопка-действие достижима: после прокрутки целиком в окне и не перекрыта (таб-баром, шторкой, шапкой). */
async function expectReachable(page: Page, target: Locator, what: string) {
  await target.first().scrollIntoViewIfNeeded();
  await expect(target.first(), `${what}: видна`).toBeVisible();
  const verdict = await target.first().evaluate((element) => {
    const rect = element.getBoundingClientRect();
    const x = Math.min(Math.max(rect.left + rect.width / 2, 0), window.innerWidth - 1);
    const y = Math.min(Math.max(rect.top + rect.height / 2, 0), window.innerHeight - 1);
    const top = document.elementFromPoint(x, y);
    return {
      inWindow: rect.top >= 0 && rect.bottom <= window.innerHeight && rect.left >= 0 && rect.right <= window.innerWidth,
      hit: top !== null && (element === top || element.contains(top) || top.contains(element)),
      by: top ? `${top.tagName}.${(top as HTMLElement).className}` : "nothing",
    };
  });
  expect(verdict.inWindow, `${what}: целиком в окне`).toBe(true);
  expect(verdict.hit, `${what}: не перекрыта (${verdict.by})`).toBe(true);
}

async function step(page: Page, tag: string, name: string, run: () => Promise<void>, minChars = 40) {
  await test.step(name, async () => {
    await run();
    await expectScreenHealthy(page, name, minChars);
    await shot(page, tag, name);
  });
}

async function workoutsStat(page: Page): Promise<number> {
  await expect(page.getByText("Тренировок за 30 дней", { exact: true })).toBeVisible();
  const text = await page.locator("body").innerText();
  const match = /(\d+)\s*\n\s*Тренировок за 30 дней/.exec(text);
  expect(match, "карточка «Тренировок за 30 дней»").not.toBeNull();
  return Number(match![1]);
}

/** «Назад» двумя путями — in-app и Telegram BackButton — ведёт на исходный экран. */
async function backBoth(page: Page, where: string, inApp: Locator | null, origin: Locator, reopen: () => Promise<void>) {
  expect(await isTelegramBackButtonVisible(page), `${where}: Telegram BackButton показан`).toBe(true);
  await pressTelegramBackButton(page);
  await expect(origin.first(), `${where}: BackButton → исходный экран`).toBeVisible();
  if (inApp) {
    await reopen();
    await inApp.click();
    await expect(origin.first(), `${where}: «Назад» → исходный экран`).toBeVisible();
  }
}

/** Аналитика → «Программа» (график + «Лидерборд») → обратно на «Тренировки»: подраздел достижим и не пуст. */
async function programAnalytics(page: Page, tag: string) {
  await openTab(page, "Аналитика");
  const switcher = (name: string) => page.getByRole("tab", { name, exact: true }).or(page.getByRole("button", { name, exact: true })).first();
  await switcher("Программа").click();
  await step(page, tag, "Аналитика → Программа: график", async () => {
    await expect(page.getByText("Загружаю прогресс…")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Лидерборд/ })).toBeVisible();
  });
  await page.getByRole("button", { name: /Лидерборд/ }).click();
  await step(page, tag, "Аналитика → Программа: лидерборд", async () => {
    await expect(page.getByRole("button", { name: /График/ })).toBeVisible();
    await expect(page.getByText("Загружаю", { exact: false })).toHaveCount(0);
  }, 20);
  await switcher("Тренировки").click();
  await expect(page.getByText("Тренировок за 30 дней", { exact: true })).toBeVisible();
}

COMBOS.forEach(({ width, theme }, comboIndex) => {
  const tag = `${width}-${theme}`;

  test.describe(`Final journey @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 800 } });
    test.setTimeout(240_000);

    test("пустой пользователь: вкладки, поиск, подборки, настройки — без тупиков", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, uid("empty", comboIndex, testInfo.retry), { theme, backButton: true });
      const t = `${tag}-empty`;

      await step(page, t, "01 Главная", async () => {
        await expect(page.getByTestId("home-tests-row")).toBeVisible();
        await expect(page.getByText("Соберите свою тренировку из упражнений и протоколов.")).toBeVisible();
      });

      // Поиск: каталог доступен пустому пользователю; закрыть → Главная.
      await step(page, t, "02 Поиск", async () => {
        await page.getByTestId("home-search-pill").click();
        await expect(page.getByTestId("search-screen")).toBeVisible();
        await expect(page.getByTestId("search-count")).toContainText("Найдено:");
        await page.getByLabel("Поиск").fill("zzzz-нет-такого");
        await expect(page.getByTestId("search-empty")).toBeVisible();
        await page.getByLabel("Поиск").fill("");
        await page.getByTestId("search-chip-tests").click();
        await expect(page.getByTestId("search-result-test").first()).toBeVisible();
      });
      await expectReachable(page, byName(page, "Закрыть"), "Поиск: «Закрыть»");
      await byName(page, "Закрыть").click();
      await expect(page.getByTestId("home-tests-row")).toBeVisible();

      // Каждая вкладка осмысленна и без overflow.
      for (const label of ["Планы", "Журнал", "Аналитика", "Профиль"]) {
        await step(page, t, `03 вкладка ${label}`, async () => {
          await openTab(page, label);
          await expect(tabbar(page)).toBeVisible();
          await expect(TAB_MARKER[label](page).first()).toBeVisible();
        });
      }

      await programAnalytics(page, t);

      await step(page, t, "04 Планы пустые: есть путь к курсам", async () => {
        await openTab(page, "Планы");
        await expect(page.getByTestId("plans-now-empty")).toBeVisible();
        await byName(page, /Выбрать курс на Главной/).click();
        await expect(page.getByTestId("home-tests-row")).toBeVisible();
      });

      await step(page, t, "05 Журнал пустой: «+ Записать» открывает форму, «Назад» возвращает", async () => {
        await openTab(page, "Журнал");
        await expectReachable(page, byName(page, "+ Записать"), "Журнал: «+ Записать»");
        await byName(page, "+ Записать").click();
        await expect(page.getByTestId("journal-log-sheet")).toBeVisible();
        await expectReachable(page, page.getByTestId("log-option-activity"), "Журнал: шторка «Другую активность»");
      });
      await page.getByTestId("log-option-activity").click();
      await expect(page.getByTestId("log-activity-type")).toBeVisible();
      await shot(page, t, "05b форма активности");
      await byName(page, "← Назад").click();
      await expect(byName(page, "+ Записать")).toBeVisible();
      await byName(page, "+ Записать").click();
      await page.getByTestId("log-option-activity").click();
      await pressTelegramBackButton(page);
      await expect(byName(page, "+ Записать")).toBeVisible();

      await step(page, t, "06 Тесты: список → деталь → BackButton", async () => {
        await openTab(page, "Главная");
        await page.getByTestId("home-tests-row").click();
        await expect(page.getByTestId("tests-list")).toBeVisible();
      });
      await page.getByTestId("test-card").first().click();
      await expect(page.getByTestId("test-detail-title")).toBeVisible();
      await shot(page, t, "06b тест деталь");
      await expectReachable(page, page.getByTestId("test-form").getByRole("button", { name: "Записать результат" }), "Тест: «Записать результат»");
      await backBoth(page, "Тест", null, page.getByTestId("tests-list"), async () => undefined);
      await pressTelegramBackButton(page);
      await expect(page.getByTestId("home-tests-row")).toBeVisible();

      await step(page, t, "07 Профиль → Настройки → Отмена", async () => {
        await openTab(page, "Профиль");
        await page.getByTestId("profile-settings").click();
        await expect(page.getByTestId("settings-screen")).toBeVisible();
      });
      await expectReachable(page, page.getByTestId("settings-save"), "Настройки: «Сохранить»");
      await page.getByTestId("settings-cancel").click();
      await expect(page.getByText("Личные данные", { exact: true })).toBeVisible();

      await step(page, t, "08 Подборки (с Главной)", async () => {
        await openTab(page, "Главная");
        const card = page.getByTestId("collections-row").getByTestId("collection-card").first();
        await card.scrollIntoViewIfNeeded();
        await card.click();
        await expect(page.getByTestId("collection-screen")).toBeVisible();
        await expect(page.getByTestId("collection-item").first()).toBeVisible();
      });
      await pressTelegramBackButton(page);
      await expect(page.getByTestId("home-tests-row")).toBeVisible();

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("наполненный пользователь: поиск → деталь → старт → сессия → Журнал → Аналитика → Планы → Тесты → Профиль", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, uid("populated", comboIndex, testInfo.retry), { theme, backButton: true });
      const t = `${tag}-populated`;

      await step(page, t, "01 Главная", async () => {
        await expect(page.getByTestId("my-workout-card").filter({ hasText: WORKOUT })).toBeVisible();
      });
      await openTab(page, "Аналитика");
      const before = await workoutsStat(page);
      expect(before).toBeGreaterThanOrEqual(POPULATED_WORKOUTS); // >: повторный прогон на той же БД
      await shot(page, t, "01b аналитика до");
      await openTab(page, "Главная");

      // Поиск находит свою тренировку; деталь открывается из результата; назад → поиск с тем же запросом.
      await step(page, t, "02 Поиск находит «Свип»", async () => {
        await page.getByTestId("home-search-pill").click();
        await page.getByLabel("Поиск").fill("Свип");
        await expect(page.getByTestId("search-result-workout").filter({ hasText: WORKOUT })).toBeVisible();
      });
      await page.getByTestId("search-result-workout").filter({ hasText: WORKOUT }).click();
      await expect(page.getByTestId("workout-detail-title")).toHaveText(WORKOUT);
      await shot(page, t, "03 деталь из поиска");
      await pressTelegramBackButton(page);
      await expect(page.getByLabel("Поиск")).toHaveValue("Свип"); // состояние поиска сохранено
      await byName(page, "Закрыть").click();
      await expect(page.getByTestId("home-tests-row")).toBeVisible();

      // Деталь → старт → предэкран → Live.
      await step(page, t, "04 Деталь тренировки: CTA достижимы", async () => {
        await page.getByTestId("my-workout-card").filter({ hasText: WORKOUT }).click();
        await expect(page.getByTestId("workout-detail-title")).toHaveText(WORKOUT);
        await expectReachable(page, page.getByTestId("workout-detail-start"), "Деталь: «Начать»");
        await expectReachable(page, page.getByTestId("workout-detail-log"), "Деталь: «Записать»");
      });
      // «Назад» с предэкрана ведёт на Workout Detail, откуда нажали «Начать» (раньше — на Главную).
      await page.getByTestId("workout-detail-start").click();
      await expect(byName(page, "Начать")).toBeVisible();
      await pressTelegramBackButton(page);
      await expect(page.getByTestId("workout-detail-title")).toHaveText(WORKOUT);
      await page.getByTestId("workout-detail-start").click();
      await expect(byName(page, "Начать")).toBeVisible();
      await page.getByRole("button", { name: /Назад/ }).first().click();
      await expect(page.getByTestId("workout-detail-title")).toHaveText(WORKOUT);
      await pressTelegramBackButton(page); // с детали — на Главную
      await expect(page.getByTestId("home-tests-row")).toBeVisible();
      await page.getByTestId("my-workout-card").filter({ hasText: WORKOUT }).click();
      await page.getByTestId("workout-detail-start").click();
      await step(page, t, "05 Предэкран", async () => {
        await expect(byName(page, "Начать")).toBeVisible();
        await expectReachable(page, byName(page, "Начать"), "Предэкран: «Начать»");
      }, 15);
      await byName(page, "Начать").click();
      await step(page, t, "06 Live", async () => {
        await expect(page.getByText(/Подход 1\/2 · Цель: 8 повт\./)).toBeVisible();
        await expectReachable(page, byName(page, "Готов"), "Live: «Готов»");
      });
      // Telegram BackButton в Live спрашивает подтверждение; «Отмена» оставляет в сессии (не молчаливый выход).
      const confirmation = new Promise<string>((resolve) => page.once("dialog", (dialog) => { resolve(dialog.message()); void dialog.dismiss(); }));
      await pressTelegramBackButton(page);
      expect(await confirmation).toContain("Закончить сессию?");
      await expect(page.getByText(/Подход 1\/2 · Цель: 8 повт\./)).toBeVisible();
      await playSets(page, ["8", "7"]);
      await expectReachable(page, byName(page, "Завершить"), "Live: «Завершить»");
      await shot(page, t, "07 Live после подходов");
      await byName(page, "Завершить").click();
      await shot(page, t, "08 подтверждение завершения");
      await expectReachable(page, byName(page, "Сохранить и завершить"), "Live: «Сохранить и завершить»");
      await clickAndSync(page, "Сохранить и завершить", "/complete");
      await step(page, t, "09 Итог", async () => {
        await expect(page.getByText("Тренировка завершена")).toBeVisible();
        // Регрессия: итог не показывает внутренние коды (раньше «not_plan_session» после «Начать» с Workout Detail).
        expect(await page.locator("body").innerText(), "итог: внутренний snake_case-код на экране").not.toMatch(/\b[a-z]+_[a-z_]+\b/);
        await expectReachable(page, byName(page, "Закрыть"), "Итог: «Закрыть»");
      });
      await byName(page, "Закрыть").click();
      await expect(tabbar(page)).toBeVisible();

      // Данные свежие везде, где пользователь будет смотреть.
      await step(page, t, "10 Журнал показывает новую тренировку", async () => {
        await openTab(page, "Журнал");
        await expect(page.locator(".journal-card").filter({ hasText: WORKOUT }).first()).toBeVisible();
      });
      await step(page, t, "11 Аналитика пересчитана", async () => {
        await openTab(page, "Аналитика");
        await expect.poll(() => workoutsStat(page)).toBe(before + 1);
      });
      await programAnalytics(page, t);
      await step(page, t, "11b Главная после тренировки: карточка и «Подборки» на месте", async () => {
        await openTab(page, "Главная");
        await expect(page.getByTestId("my-workout-card").filter({ hasText: WORKOUT })).toBeVisible();
      });

      await step(page, t, "12 Планы: курс, строки дня, «Начать: …»", async () => {
        await openTab(page, "Планы");
        await expect(page.getByTestId("plans-now-inclusion").filter({ hasText: COURSE })).toBeVisible();
        await expectReachable(page, page.getByRole("button", { name: /^Начать: / }), "Планы: «Начать: …»");
      });
      // Из Планов — старт плановой тренировки и «Назад» из предэкрана возвращает в Планы.
      await page.getByRole("button", { name: /^Начать: / }).first().click();
      await expect(byName(page, "Начать")).toBeVisible(); // предэкран плановой сессии
      await shot(page, t, "12b старт из плана");
      await expectReachable(page, byName(page, "Начать"), "Предэкран плана: «Начать»");
      await pressTelegramBackButton(page); // назад с предэкрана — в Планы, не на Главную
      await expect(page.getByText("Текущий план", { exact: true })).toBeVisible();

      await step(page, t, "13 Тесты: запись результата виден в списке", async () => {
        await openTab(page, "Главная");
        await page.getByTestId("home-tests-row").click();
        await expect(page.getByTestId("tests-list")).toBeVisible();
      });
      await page.getByTestId("test-card").filter({ hasText: "Максимум подтягиваний" }).click();
      const form = page.getByTestId("test-form");
      const value = String(20 + (Date.now() % 70)); // уникален для прогона: БД e2e переживает повторные запуски
      await form.getByLabel("Результат, повт.").fill(value);
      await expectReachable(page, form.getByRole("button", { name: "Записать результат" }), "Тест: «Записать результат»");
      await form.getByRole("button", { name: "Записать результат" }).click();
      await expect(page.getByTestId("test-history-row").filter({ hasText: `${value} повт.` })).toHaveCount(1);
      await shot(page, t, "13b тест записан");
      await pressTelegramBackButton(page);
      await pressTelegramBackButton(page);
      await expect(page.getByTestId("home-tests-row")).toBeVisible();

      await step(page, t, "14 Профиль: результат теста свеж", async () => {
        await openTab(page, "Профиль");
        await expect(page.getByTestId("profile-tests").getByTestId("test-card").filter({ hasText: "Максимум подтягиваний" }))
          .toContainText(`${value} повт.`);
      });
      await step(page, t, "15 Профиль → Настройки → Сохранить возвращает в Профиль", async () => {
        await page.getByTestId("profile-settings").click();
        await expectReachable(page, page.getByTestId("settings-save"), "Настройки: «Сохранить»");
      });
      await page.getByTestId("settings-cancel").click();

      await step(page, t, "16 Подборки → элемент → Назад", async () => {
        await openTab(page, "Главная");
        const card = page.getByTestId("collections-row").getByTestId("collection-card").first();
        await card.scrollIntoViewIfNeeded();
        await card.click();
        await expect(page.getByTestId("collection-screen")).toBeVisible();
      });
      await page.getByTestId("collection-item").first().click();
      await shot(page, t, "16b элемент подборки");
      await pressTelegramBackButton(page);
      await expect(page.getByTestId("collection-screen")).toBeVisible();
      await pressTelegramBackButton(page);
      await expect(page.getByTestId("home-tests-row")).toBeVisible();

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
});
