import { expect, test, type Locator, type Page } from "@playwright/test";

import { clickAndSync, noWakeLock, playSets } from "../../fixtures/builderFlow";
import {
  captureDownloads, COMBOS, expectScreenHealthy, openTab,
} from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import { isTelegramBackButtonVisible, pressTelegramBackButton } from "../../fixtures/telegramMock";

// Crimpd parity — «Full sweep» (#277, docs/CRIMPD_FULL_PARITY_8_5.md, все строки).
//
// Что прогоняется: 320 и 390 px × светлая и тёмная тема × пустой и наполненный пользователь.
//   1. «Вкладки»      — все пять вкладок: осмысленный (не пустой) контент, нет горизонтального
//                       overflow, нет ошибок страницы/консоли/API.
//   2. «Переходы»     — таблица FLOWS: у каждого основного действия экрана есть пункт назначения
//                       (нет тупиков), с него можно вернуться на исходный экран (кнопка «Назад»/
//                       «Отмена»/Telegram BackButton). НОВЫЕ ОБЛАСТИ (#275 / #271 / #276) —
//                       добавить записи в FLOWS ниже (см. «PLUG IN»), код теста не трогать.
//   3. «Потоки»       — сквозные сценарии с данными (мутируют — у каждого свой пользователь):
//                       Главная → деталь → старт → лог → завершение → Журнал → Аналитика → экспорт;
//                       Тесты (запись → тренд); Настройки (единицы); Планы (недели).
// Селекторы — роли/тексты/data-testid (не CSS-классы), чтобы визуальный рестайл (#280) их не ломал.
// Скриншоты — только артефакты Playwright при падении (конфиг). Сиды: scripts/e2e_seed.py
// `sweep_empty` / `sweep_populated` (см. scripts/e2e_seed_all.sh, блок «Full sweep (#277)»).

type Mode = "empty" | "populated";
const MODES: readonly Mode[] = ["empty", "populated"];

// Базы telegram_id: +индекс комбинации (320 light / 320 dark / 390 light / 390 dark), +100 на retry.
const BASE = {
  empty: 999_601, populated: 999_611, workout: 999_621, tests: 999_631, settings: 999_641, plans: 999_651,
} as const;
const uid = (base: number, comboIndex: number, retry: number) => base + comboIndex + retry * 100;

const WORKOUT = "Свип: тренировка";
const COURSE = "Свип: курс";
const HANG = "Вис на перекладине, сек";
const ELECTIVE = "Факультатив — 3 минуты подтягиваний"; // #279, сидится вместе с наполненным пользователем
// Завершённых тренировок за 30 дней у наполненного пользователя: 3 «Подтягивания» + «Бег» + 2 плановые + 2 факультатива.
const POPULATED_WORKOUTS = 8;

const tabbar = (page: Page) => page.locator(".bottom-tabbar");
const homeMarker = (page: Page) => page.getByTestId("home-tests-row");
const plansMarker = (page: Page) => page.getByText("Текущий план", { exact: true });
const journalMarker = (page: Page) => page.getByRole("button", { name: "+ Записать" });
const analyticsMarker = (page: Page) => page.getByText("Тренировок за 30 дней", { exact: true });
const profileMarker = (page: Page) => page.getByText("Личные данные", { exact: true });

/** Число из карточки аналитики «<N> / Тренировок за 30 дней». */
async function workoutsStat(page: Page): Promise<number> {
  await expect(analyticsMarker(page)).toBeVisible();
  const text = await page.locator("body").innerText();
  const match = /(\d+)\s*\n\s*Тренировок за 30 дней/.exec(text);
  expect(match, "карточка «Тренировок за 30 дней»").not.toBeNull();
  return Number(match![1]);
}

/** Вкладки: маркер экрана и маркеры состояния «пусто» / «наполнено» для посеянных пользователей. */
const TABS: {
  label: string;
  shell: (page: Page) => Locator;
  state: Record<Mode, (page: Page) => Locator>;
}[] = [
  {
    label: "Главная", shell: homeMarker,
    state: {
      empty: (page) => page.getByText("Соберите свою тренировку из упражнений и протоколов."),
      populated: (page) => page.getByTestId("my-workout-card").filter({ hasText: WORKOUT }),
    },
  },
  {
    label: "Планы", shell: plansMarker,
    state: {
      empty: (page) => page.getByTestId("plans-now-empty"),
      populated: (page) => page.getByTestId("plans-now-inclusion").filter({ hasText: COURSE }),
    },
  },
  {
    label: "Журнал", shell: journalMarker,
    state: {
      empty: (page) => page.getByText("В этом месяце тренировок нет"),
      populated: (page) => page.getByText(ELECTIVE).first(),
    },
  },
  {
    label: "Аналитика", shell: analyticsMarker,
    state: {
      empty: (page) => page.getByTestId("export-card"),
      populated: (page) => page.getByTestId("analytics-metric-total").filter({ hasText: `Всего тренировок: ${POPULATED_WORKOUTS}` }),
    },
  },
  {
    label: "Профиль", shell: profileMarker,
    state: {
      empty: (page) => page.getByTestId("test-card").filter({ hasText: "Ещё не проходили" }).first(),
      populated: (page) => page.getByTestId("test-card").filter({ hasText: "12 повт." }),
    },
  },
];

// --- Переходы: «каждое основное действие куда-то ведёт и возвращает назад» ----------------------

type Exit = { button: Locator } | { tab: string } | "telegram";

type Ctx = { page: Page; mode: Mode };
type Flow = { id: string; modes: readonly Mode[]; run: (ctx: Ctx) => Promise<void> };

/**
 * open → пункт назначения (маркеры видны, экран не пустой и не шире окна) → выход → исходный
 * экран снова на месте. Выход «telegram» дополнительно проверяет, что BackButton показан.
 */
async function visit(
  page: Page,
  step: {
    where: string; open: () => Promise<void>; dest: Locator[]; exit: Exit; origin: Locator;
    inside?: () => Promise<void>; minChars?: number;
  },
) {
  await test.step(step.where, async () => {
    await step.open();
    for (const marker of step.dest) {
      await expect(marker.first(), `«${step.where}»: пункт назначения`).toBeVisible();
    }
    await expectScreenHealthy(page, step.where, step.minChars);
    await step.inside?.();
    if (step.exit === "telegram") {
      expect(await isTelegramBackButtonVisible(page), `«${step.where}»: Telegram BackButton`).toBe(true);
      await pressTelegramBackButton(page);
    } else if ("button" in step.exit) {
      await step.exit.button.click();
    } else {
      await openTab(page, step.exit.tab);
    }
    await expect(step.origin.first(), `«${step.where}»: возврат на исходный экран`).toBeVisible();
    await expectScreenHealthy(page, `${step.where} (после возврата)`);
  });
}

const byName = (page: Page, name: string | RegExp, exact = true) => page.getByRole("button", { name, exact });

// PLUG IN: новые области кампании (Plans scheduling #275, Collections #271, Peer insights #276)
// добавляются сюда одной записью {id, modes, run}; run использует visit(...) и маркеры экрана.
const FLOWS: Flow[] = [
  // ---- Главная ------------------------------------------------------------------------------
  {
    id: "Главная: поиск → результаты/пусто → закрыть", modes: MODES,
    run: async ({ page }) => {
      await visit(page, {
        where: "Главная → поиск", open: () => page.getByTestId("home-search-pill").click(),
        dest: [page.getByTestId("search-count")], exit: { button: byName(page, "Закрыть") }, origin: homeMarker(page),
        inside: async () => {
          await page.getByLabel("Поиск").fill("Свип");
          await expect(page.getByTestId("search-count")).not.toHaveText("Найдено: 0");
          await page.getByLabel("Поиск").fill("ъъъъъъъъ");
          await expect(page.getByTestId("search-empty")).toBeVisible();
        },
      });
    },
  },
  {
    id: "Главная: «+» → создать / сегодня / журнал / отмена", modes: MODES,
    run: async ({ page }) => {
      const sheet = page.getByRole("dialog", { name: "Быстрые действия" });
      const plus = () => page.getByTestId("home-plus").click();
      await visit(page, {
        where: "«+» → шторка", open: plus, dest: [sheet], exit: { button: sheet.getByRole("button", { name: "Отмена" }) },
        origin: homeMarker(page),
      });
      await expect(sheet).toHaveCount(0);
      await visit(page, {
        where: "«+» → Создать тренировку", open: async () => { await plus(); await sheet.getByRole("button", { name: "Создать тренировку" }).click(); },
        dest: [page.getByText("Новая тренировка", { exact: true })], exit: "telegram", origin: homeMarker(page),
      });
      await visit(page, {
        where: "«+» → Записать в журнал", open: async () => { await plus(); await sheet.getByRole("button", { name: "Записать в журнал" }).click(); },
        dest: [page.getByTestId("journal-log-sheet")],
        exit: { button: page.getByTestId("journal-log-sheet").getByRole("button", { name: "Отмена" }) }, origin: journalMarker(page),
      });
      await openTab(page, "Главная");
      await visit(page, {
        where: "«+» → Тренировка на сегодня", open: async () => { await plus(); await sheet.getByRole("button", { name: "Тренировка на сегодня" }).click(); },
        dest: [plansMarker(page)], exit: { tab: "Главная" }, origin: homeMarker(page),
      });
    },
  },
  {
    id: "Главная: Тесты → список → деталь теста → назад", modes: MODES,
    run: async ({ page }) => {
      await visit(page, {
        where: "Главная → Тесты", open: () => page.getByTestId("home-tests-row").click(),
        dest: [page.getByTestId("test-card")], exit: "telegram", origin: homeMarker(page),
        inside: async () => {
          await expect(page.getByTestId("test-card")).toHaveCount(3);
          await visit(page, {
            where: "Тесты → деталь", open: () => page.getByTestId("test-card").first().click(),
            dest: [page.getByTestId("test-detail-title"), page.getByTestId("test-form")], exit: "telegram",
            origin: page.getByTestId("test-card").first(),
          });
        },
      });
    },
  },
  {
    id: "Главная: карточка программы → деталь → назад", modes: MODES,
    run: async ({ page, mode }) => {
      await visit(page, {
        where: "Главная → программа", open: () => byName(page, new RegExp(COURSE), false).first().click(),
        dest: [page.getByText("Расписание · 8 нед."), mode === "populated" ? page.getByText("В плане ✓") : byName(page, "Добавить в план")],
        exit: { button: byName(page, "← Назад") }, origin: homeMarker(page),
      });
    },
  },
  {
    id: "Главная: «Создать тренировку» (пустой пользователь) → редактор → назад", modes: ["empty"],
    run: async ({ page }) => {
      await visit(page, {
        where: "Главная → Создать тренировку", open: () => byName(page, "Создать тренировку").click(),
        dest: [page.getByText("Новая тренировка", { exact: true })], exit: "telegram", origin: homeMarker(page),
      });
    },
  },
  {
    id: "Главная: избранное и «Мои тренировки» → деталь → «Записать» / «В план» / «Изменить» → назад", modes: ["populated"],
    run: async ({ page }) => {
      const detail = page.getByTestId("workout-detail");
      await visit(page, {
        where: "Избранное → деталь", open: () => page.getByTestId("favorite-card").first().click(),
        dest: [detail, page.getByTestId("workout-detail-start"), page.getByTestId("workout-detail-log")], exit: "telegram",
        origin: homeMarker(page),
      });
      await page.getByTestId("my-workout-card").filter({ hasText: WORKOUT }).click();
      await expect(detail).toBeVisible();
      await visit(page, {
        where: "Деталь → Записать", open: () => page.getByTestId("workout-detail-log").click(),
        dest: [page.getByTestId("journal-log-form")], exit: { tab: "Главная" }, origin: homeMarker(page),
      });
      await page.getByTestId("my-workout-card").filter({ hasText: WORKOUT }).click();
      await visit(page, {
        where: "Деталь → Добавить в план", open: () => byName(page, "Добавить в план").click(),
        dest: [byName(page, "Добавить", true)], exit: "telegram", origin: detail,
      });
      await visit(page, {
        where: "Деталь → Редактировать", open: () => byName(page, "Редактировать").click(),
        dest: [page.getByText("Редактировать тренировку")], exit: "telegram", origin: detail,
      });
      await pressTelegramBackButton(page);
      await expect(homeMarker(page)).toBeVisible();
    },
  },
  {
    // #271: глобальная подборка «E2E: подборка» создаётся сидом `collections` (scripts/e2e_seed_all.sh).
    id: "Главная: «Подборки» → экран подборки → программа / упражнение → назад", modes: MODES,
    run: async ({ page }) => {
      const row = page.getByTestId("collections-row");
      const screen = page.getByTestId("collection-screen");
      await expect(row).toBeVisible();
      await visit(page, {
        where: "Главная → подборка", open: () => row.getByTestId("collection-card").filter({ hasText: "E2E: подборка" }).click(),
        dest: [screen, page.getByTestId("collection-title"), page.getByTestId("collection-item")],
        exit: { button: byName(page, "← Назад") }, origin: row,
        inside: async () => {
          await visit(page, {
            where: "Подборка → программа", open: () => page.getByTestId("collection-item").first().click(),
            dest: [page.getByTestId("program-detail-title")], exit: { button: byName(page, "← Назад") }, origin: screen,
          });
        },
      });
    },
  },
  // ---- Планы --------------------------------------------------------------------------------
  {
    id: "Планы: Сейчас / Завершённые", modes: MODES,
    run: async ({ page }) => {
      await openTab(page, "Планы");
      await page.getByRole("tab", { name: "Завершённые" }).click();
      await expect(page.getByTestId("plans-completed")).toBeVisible();
      await expectScreenHealthy(page, "Планы: Завершённые");
      await page.getByRole("tab", { name: "Сейчас" }).click();
      await expect(page.getByTestId("plans-now-card")).toBeVisible();
    },
  },
  {
    id: "Планы: «Мои тренировки» → список → назад", modes: MODES,
    run: async ({ page, mode }) => {
      await openTab(page, "Планы");
      await visit(page, {
        where: "Планы → Мои тренировки", open: () => byName(page, "Мои тренировки").click(),
        dest: [mode === "populated" ? byName(page, new RegExp(WORKOUT), false) : page.getByText("Мои тренировки", { exact: true })],
        exit: "telegram", origin: plansMarker(page),
      });
    },
  },
  {
    id: "Планы: «Перенести» / «+ Добавить упражнение» / «Начать» → экран → назад", modes: ["populated"],
    run: async ({ page }) => {
      await openTab(page, "Планы");
      await visit(page, {
        where: "Планы → Перенести", open: () => byName(page, "Перенести").first().click(),
        dest: [page.getByText("Перенести", { exact: true }), byName(page, "Сохранить")], exit: "telegram", origin: plansMarker(page),
      });
      await visit(page, {
        where: "Планы → Добавить упражнение", open: () => byName(page, "+ Добавить упражнение").click(),
        dest: [page.getByText("День", { exact: true }), byName(page, "Свободный пул")], exit: { tab: "Планы" }, origin: plansMarker(page),
      });
      await visit(page, {
        where: "Планы → Начать", open: () => byName(page, "Начать").first().click(),
        dest: [byName(page, "Начать")], exit: "telegram", origin: plansMarker(page), minChars: 15, // предэкран: название + «Начать»
      });
    },
  },
  // ---- Журнал -------------------------------------------------------------------------------
  {
    id: "Журнал: «+ Записать» → тренировка / активность → назад", modes: MODES,
    run: async ({ page }) => {
      await openTab(page, "Журнал");
      const sheet = page.getByTestId("journal-log-sheet");
      for (const choice of ["Тренировку из моих", "Другую активность"]) {
        await visit(page, {
          where: `Журнал → Записать → ${choice}`,
          open: async () => { await journalMarker(page).click(); await sheet.getByRole("button", { name: choice }).click(); },
          dest: [page.getByTestId("journal-log-form"), page.getByTestId("log-save")], exit: { button: byName(page, "← Назад") },
          origin: journalMarker(page),
        });
      }
      await journalMarker(page).click();
      await sheet.getByRole("button", { name: "Отмена" }).click();
      await expect(sheet).toHaveCount(0);
    },
  },
  {
    id: "Журнал: календарь и переключение месяцев", modes: MODES,
    run: async ({ page }) => {
      await openTab(page, "Журнал");
      const month = page.getByRole("button", { name: /^(?:Предыдущий|Следующий) месяц$/ });
      await expect(month).toHaveCount(2);
      await page.getByRole("button", { name: /20\d\d ▾$/ }).click();
      await expect(page.getByText("Пн", { exact: true })).toBeVisible();
      await expectScreenHealthy(page, "Журнал: календарь");
      const label = page.getByRole("button", { name: /20\d\d ▴$/ });
      const before = await label.innerText();
      await month.first().click();
      await expect(label).not.toHaveText(before);
      await month.last().click();
      await expect(label).toHaveText(before);
      await label.click();
      await expect(page.getByText("Пн", { exact: true })).toHaveCount(0);
    },
  },
  {
    id: "Журнал: карточка (факультатив #279) → деталь с «Изменить» и «Удалить» → назад", modes: ["populated"],
    run: async ({ page }) => {
      await openTab(page, "Журнал");
      await visit(page, {
        where: "Журнал → факультатив", open: () => page.getByText(ELECTIVE).first().click(),
        dest: [byName(page, /Изменить/, false), byName(page, /Удалить/, false)], exit: { button: byName(page, "← Назад") },
        origin: journalMarker(page),
      });
    },
  },
  // ---- Аналитика ----------------------------------------------------------------------------
  {
    id: "Аналитика: метрика, период, (i)", modes: MODES,
    run: async ({ page }) => {
      await openTab(page, "Аналитика");
      const card = page.getByTestId("analytics-metrics");
      for (const metric of ["Минуты", "Тренировки"]) {
        await card.getByRole("tablist", { name: "Метрика" }).getByRole("tab", { name: metric }).click();
        await expect(card.getByRole("tablist", { name: "Метрика" }).getByRole("tab", { name: metric })).toHaveAttribute("aria-selected", "true");
      }
      for (const range of ["3 мес", "Свой", "1 мес"]) {
        await card.getByRole("tablist", { name: "Период" }).getByRole("tab", { name: range }).click();
        await expect(card.getByRole("tablist", { name: "Период" }).getByRole("tab", { name: range })).toHaveAttribute("aria-selected", "true");
        await expectScreenHealthy(page, `Аналитика: ${range}`);
      }
      const dialog = page.getByRole("dialog", { name: "Что значат метрики" });
      await card.getByRole("button", { name: "Что значат метрики" }).click();
      await expect(dialog).toBeVisible();
      await dialog.getByRole("button", { name: "Закрыть" }).click();
      await expect(dialog).toHaveCount(0);
    },
  },
  {
    id: "Аналитика: «Скачать» → ссылка на CSV работает", modes: MODES,
    run: async ({ page }) => {
      await openTab(page, "Аналитика");
      const link = page.waitForResponse((r) => r.url().endsWith("/api/v2/export/link") && r.request().method() === "POST");
      await page.getByTestId("export-download").click();
      expect((await link).status()).toBe(200);
      await expect.poll(async () => {
        const captured = await page.evaluate(() => (window as unknown as { __captured: { downloads: unknown[]; opened: unknown[] } }).__captured);
        return captured.downloads.length + captured.opened.length;
      }).toBe(1);
    },
  },
  // ---- Профиль ------------------------------------------------------------------------------
  {
    // #276: карточка «Сравнение с похожими» на детали теста — всегда в одном из состояний, без пустого места.
    id: "Тест → «Сравнение с похожими» (результат / мало данных / нет результата) → назад", modes: MODES,
    run: async ({ page, mode }) => {
      await openTab(page, "Профиль");
      const name = mode === "populated" ? "Максимум подтягиваний" : HANG;
      await visit(page, {
        where: "Профиль → тест → сравнение", open: () => page.getByTestId("profile-tests").getByTestId("test-card").filter({ hasText: name }).click(),
        dest: [page.getByTestId("peer-insights-title")], exit: "telegram", origin: profileMarker(page),
        inside: async () => {
          const card = page.getByTestId("peer-insights");
          await expect(card.getByTestId("peer-insights-loading")).toHaveCount(0);
          await expect(card.getByTestId("peer-insights-error")).toHaveCount(0);
          await expect(card.locator('[data-testid^="peer-insights-"]:not([data-testid="peer-insights-title"])').first()).toBeVisible();
        },
      });
    },
  },
  {
    id: "Профиль: ⚙️ настройки → отмена", modes: MODES,
    run: async ({ page }) => {
      await openTab(page, "Профиль");
      await visit(page, {
        where: "Профиль → Настройки", open: () => page.getByTestId("profile-settings").click(),
        dest: [page.getByTestId("settings-screen"), page.getByTestId("settings-save")], exit: { button: page.getByTestId("settings-cancel") },
        origin: profileMarker(page),
      });
    },
  },
  {
    id: "Профиль: изменить профиль / подписка / ачивки / справка / резины → назад", modes: MODES,
    run: async ({ page }) => {
      await openTab(page, "Профиль");
      const screens: [string, RegExp, Locator, Locator][] = [
        ["Изменить профиль", /Изменить$/, page.getByText("Изменить профиль", { exact: true }), byName(page, "Назад")],
        ["Подписка", /Подробнее о подписке/, page.getByText("Статус", { exact: true }), byName(page, "← Профиль")],
        ["Ачивки", /Ачивок/, page.getByText("Ачивки", { exact: true }), byName(page, "← Назад")],
        ["Как выбрать резину", /Как выбрать резину/, page.getByText("Тренироваться можно где угодно", { exact: false }), byName(page, "← Назад")],
        ["Мои резины", /Переименовать или удалить/, page.getByText("Мои резины", { exact: true }), byName(page, "← Назад")],
      ];
      for (const [where, opener, dest, back] of screens) {
        await visit(page, {
          where: `Профиль → ${where}`, open: () => byName(page, opener, false).first().click(),
          dest: [dest], exit: { button: back }, origin: profileMarker(page),
        });
      }
    },
  },
  {
    id: "Профиль: вес / рост → история замеров → назад; тест → деталь → назад", modes: MODES,
    run: async ({ page }) => {
      await openTab(page, "Профиль");
      await visit(page, {
        where: "Профиль → вес", open: () => page.getByTestId("profile-weight").click(),
        dest: [page.getByText("Сейчас:", { exact: false }), page.getByTestId("body-metrics-back")],
        exit: { button: page.getByTestId("body-metrics-back") }, origin: profileMarker(page),
      });
      await visit(page, {
        where: "Профиль → тест", open: () => page.getByTestId("profile-tests").getByTestId("test-card").first().click(),
        dest: [page.getByTestId("test-detail-title")], exit: "telegram", origin: profileMarker(page),
      });
    },
  },
];

// --- Известные дефекты (ожидаемо падают, пока не исправлены; test.fail() сообщит, когда починят) --

const KNOWN_DEFECTS: { id: string; modes: readonly Mode[]; title: string; run: (ctx: Ctx) => Promise<void> }[] = [
  {
    id: "D1", modes: ["populated"],
    title: "Деталь тренировки → «Записать» → «← Назад» возвращает на деталь, а не в Журнал",
    run: async ({ page }) => {
      await page.getByTestId("my-workout-card").filter({ hasText: WORKOUT }).click();
      await page.getByTestId("workout-detail-log").click();
      await expect(page.getByTestId("journal-log-form")).toBeVisible();
      await byName(page, "← Назад").click();
      await expect(page.getByTestId("workout-detail")).toBeVisible();
    },
  },
  {
    id: "D2", modes: ["populated"],
    title: "Профиль учитывает завершённые тренировки Журнала (сейчас — только legacy-историю: «Тренировок пока не было.»)",
    run: async ({ page }) => {
      await openTab(page, "Профиль");
      await expect(profileMarker(page)).toBeVisible();
      await expect(page.getByText("Тренировок пока не было.")).toHaveCount(0);
    },
  },
  {
    id: "D3", modes: ["empty"],
    title: "Планы без курсов: подсказка «Добавьте курс на Главной» — с кнопкой-переходом (сейчас — просто текст)",
    run: async ({ page }) => {
      await openTab(page, "Планы");
      await expect(page.getByTestId("plans-now-empty")).toBeVisible();
      await expect(page.getByTestId("plans-now-card").getByRole("button")).not.toHaveCount(0);
    },
  },
];

// --- Вкладки + переходы -----------------------------------------------------------------------

COMBOS.forEach(({ width, theme }, comboIndex) => {
  for (const mode of MODES) {
    test.describe(`Full sweep @${width}px ${theme} ${mode}`, () => {
      test.use({ viewport: { width, height: 800 } });
      test.setTimeout(150_000);

      test("вкладки: непустой контент, без overflow и ошибок", async ({ page }, testInfo) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, uid(BASE[mode], comboIndex, testInfo.retry), { theme });
        for (const tab of TABS) {
          await openTab(page, tab.label);
          await expect(tab.shell(page).first(), `${tab.label}: экран`).toBeVisible();
          await expect(tab.state[mode](page).first(), `${tab.label}: состояние «${mode}»`).toBeVisible();
          await expectScreenHealthy(page, `${tab.label} (${mode})`);
          await expect(tabbar(page)).toBeVisible();
        }
        // Тема применена: фон страницы тёмный/светлый (по яркости, не по точному цвету — цвета рестайлятся).
        const luminance = await page.evaluate(() => {
          const [r, g, b] = getComputedStyle(document.body).backgroundColor.match(/\d+(?:\.\d+)?/g)!.map(Number);
          return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
        });
        if (theme === "dark") {
          expect(luminance, "тёмная тема: фон").toBeLessThan(0.35);
        } else {
          expect(luminance, "светлая тема: фон").toBeGreaterThan(0.65);
        }
        expect(noWakeLock(consoleErrors)).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      {
        for (const defect of KNOWN_DEFECTS.filter((candidate) => candidate.modes.includes(mode))) {
          test(`известный дефект ${defect.id}: ${defect.title}`, async ({ page }, testInfo) => {
            test.fail(true, "см. комментарий #277: дефект ещё не исправлен — снять test.fail после исправления");
            await openAppAs(page, uid(BASE[mode], comboIndex, testInfo.retry), { theme, backButton: true });
            await defect.run({ page, mode });
          });
        }
      }

      test("переходы: основные действия ведут дальше и возвращают назад", async ({ page }, testInfo) => {
        await captureDownloads(page);
        const { consoleErrors, apiFailures } = await openAppAs(page, uid(BASE[mode], comboIndex, testInfo.retry), { theme, backButton: true });
        await expect(homeMarker(page)).toBeVisible();
        for (const flow of FLOWS.filter((candidate) => candidate.modes.includes(mode))) {
          await test.step(flow.id, async () => {
            await page.reload({ waitUntil: "networkidle" });
            await expect(homeMarker(page)).toBeVisible();
            await flow.run({ page, mode });
          });
        }
        expect(noWakeLock(consoleErrors)).toEqual([]);
        expect(apiFailures).toEqual([]);
      });
    });
  }
});

// --- Потоки с данными (наполненный пользователь; мутируют — каждый поток на своём id) ----------

COMBOS.forEach(({ width, theme }, comboIndex) => {
  test.describe(`Full sweep flows @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 800 } });
    test.setTimeout(150_000);

    test("тренировка: Главная → деталь → старт → лог → завершение → Журнал → Аналитика → экспорт", async ({ page }, testInfo) => {
      const downloads = await captureDownloads(page);
      const { consoleErrors, apiFailures } = await openAppAs(page, uid(BASE.workout, comboIndex, testInfo.retry), { theme });

      await openTab(page, "Аналитика");
      const before = await workoutsStat(page);
      expect(before).toBe(POPULATED_WORKOUTS);
      await openTab(page, "Главная");

      // Главная → деталь → «Начать» → предэкран → живая сессия.
      await page.getByTestId("my-workout-card").filter({ hasText: WORKOUT }).click();
      await expect(page.getByTestId("workout-detail-title")).toHaveText(WORKOUT);
      await expectScreenHealthy(page, "Деталь тренировки");
      await page.getByTestId("workout-detail-start").click();
      await expect(byName(page, "Начать")).toBeVisible();
      await expectScreenHealthy(page, "Предэкран", 15); // название + «Начать», без вкладок
      await byName(page, "Начать").click();
      await expect(page.getByText("Живая тренировка")).toBeVisible();
      await expect(page.getByText(/Подход 1\/2 · Цель: 8 повт\./)).toBeVisible();
      await expectScreenHealthy(page, "Живая тренировка");

      // Лог двух подходов → завершение → итог.
      await playSets(page, ["8", "7"]);
      await expectScreenHealthy(page, "Живая тренировка: после подходов");
      await byName(page, "Завершить").click();
      await clickAndSync(page, "Сохранить и завершить", "/complete");
      await expect(page.getByText("Тренировка завершена")).toBeVisible();
      await expect(page.getByText("Подход 1: 8 повт.")).toBeVisible();
      await expectScreenHealthy(page, "Итог тренировки");
      await byName(page, "Закрыть").click();
      await expect(tabbar(page)).toBeVisible();

      // Журнал показывает запись (сегодняшняя — по названию Workout и значениям подходов).
      await openTab(page, "Журнал");
      await expect(page.getByText(WORKOUT, { exact: true }).first()).toBeVisible();
      await expect(page.getByText("8 · 7", { exact: true }).first()).toBeVisible();
      await expectScreenHealthy(page, "Журнал после тренировки");

      // Аналитика пересчитана: +1 тренировка.
      await openTab(page, "Аналитика");
      await expect.poll(() => workoutsStat(page)).toBe(before + 1);
      await expect(page.getByTestId("analytics-metric-total")).toContainText(`Всего тренировок: ${before + 1}`);
      await expectScreenHealthy(page, "Аналитика после тренировки");

      // Экспорт: подписанная ссылка отдаёт CSV, в котором есть новая тренировка.
      const link = page.waitForResponse((r) => r.url().endsWith("/api/v2/export/link") && r.request().method() === "POST");
      await page.getByTestId("export-download").click();
      expect((await link).status()).toBe(200);
      await expect.poll(async () => (await downloads.read()).downloads.length + (await downloads.read()).opened.length).toBe(1);
      const captured = await downloads.read();
      const url = captured.downloads[0]?.url ?? captured.opened[0];
      const csv = await page.request.get(url);
      expect(csv.status()).toBe(200);
      expect((await csv.text()).replace(/^﻿/, "")).toContain(WORKOUT);

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("тесты: запись → тренд → Профиль", async ({ page }, testInfo) => {
      page.on("dialog", (dialog) => void dialog.accept());
      const { consoleErrors, apiFailures } = await openAppAs(page, uid(BASE.tests, comboIndex, testInfo.retry), { theme, backButton: true });
      const card = (name: string) => page.getByTestId("test-card").filter({ hasText: name });
      const rows = page.getByTestId("test-history-row");

      await page.getByTestId("home-tests-row").click();
      await expect(card("Максимум подтягиваний").getByTestId("test-card-trend")).toBeVisible(); // посеяно: 10 → 12
      await expect(card(HANG).getByTestId("test-card-trend")).toHaveCount(0);
      await card(HANG).click();
      await expect(page.getByTestId("test-history-empty")).toBeVisible();

      const form = page.getByTestId("test-form");
      const record = async (value: string, date?: string) => {
        if (date) {
          await form.getByLabel("Дата").fill(date);
        }
        await form.getByLabel("Результат, сек").fill(value);
        await form.getByRole("button", { name: "Записать результат" }).click();
      };
      const daysAgo = (days: number) =>
        new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Moscow" }).format(new Date(Date.now() - days * 86_400_000));
      await record("40");
      await expect(rows).toHaveCount(1);
      await expect(page.getByTestId("test-chart-empty")).toBeVisible();
      await record("45", daysAgo(2));
      await expect(rows).toHaveCount(2);
      await expect(page.getByTestId("test-chart")).toHaveAttribute("data-points", "2");
      await expectScreenHealthy(page, "Тест: график");

      await pressTelegramBackButton(page);
      await expect(card(HANG).getByTestId("test-card-trend")).toBeVisible(); // тренд после второго замера
      await expect(card(HANG).getByTestId("test-card-last")).toContainText("40 сек");
      await pressTelegramBackButton(page);
      await expect(homeMarker(page)).toBeVisible();

      // Профиль: тот же результат в карточке «Тесты».
      await openTab(page, "Профиль");
      await expect(page.getByTestId("profile-tests").getByTestId("test-card").filter({ hasText: HANG }))
        .toContainText("40 сек");
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("настройки → единицы: профиль и форма пересчитываются, хранение метрическое", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, uid(BASE.settings, comboIndex, testInfo.retry), { theme });
      await openTab(page, "Профиль");
      await expect(page.getByTestId("profile-weight")).toHaveText("Вес: 75 кг");
      await page.getByTestId("profile-settings").click();
      await page.getByTestId("settings-weight-unit").getByRole("button", { name: "фунты" }).click();
      await page.getByTestId("settings-height-unit").getByRole("button", { name: "дюймы" }).click();
      await expectScreenHealthy(page, "Настройки: единицы");
      await page.getByTestId("settings-save").click();
      await expect(page.getByTestId("profile-weight")).toHaveText("Вес: 165.3 фунт.");
      await expect(page.getByTestId("profile-height")).toHaveText("Рост: 70.9 дюйм.");

      // История замеров показывается в выбранных единицах и переживает перезагрузку.
      await page.reload();
      await openTab(page, "Профиль");
      await expect(page.getByTestId("profile-weight")).toHaveText("Вес: 165.3 фунт.");
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("планы: назад к прошлой неделе, вперёд (#275) — будущая неделя, копирование с подтверждением, перенос", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, uid(BASE.plans, comboIndex, testInfo.retry), { theme, backButton: true });
      await openTab(page, "Планы");
      const label = page.getByTestId("plan-week-label");
      const next = page.getByRole("button", { name: "Следующая неделя" });
      const prev = page.getByRole("button", { name: "Предыдущая неделя" });
      const copyButton = page.getByRole("button", { name: "Скопировать неделю → на следующую" });

      await expect(label).toContainText(/Неделя \d+ · \d{1,2} \S+ – \d{1,2} \S+/);
      await expect(page.getByRole("button", { name: "Начать", exact: true })).not.toHaveCount(0);
      await expect(page.getByRole("button", { name: "+ Добавить упражнение" })).toBeVisible();
      await expectScreenHealthy(page, "Планы: текущая неделя");
      const current = await label.innerText();

      // Прошлая неделя: только чтение (нет «Начать», «+ Добавить упражнение»).
      await prev.click();
      await expect(label).not.toHaveText(current);
      await expect(page.getByTestId("plan-item-counter")).toHaveText(["1/1"]);
      await expect(page.getByRole("button", { name: "Начать", exact: true })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "+ Добавить упражнение" })).toHaveCount(0);
      await expectScreenHealthy(page, "Планы: прошлая неделя");
      await next.click();
      await expect(label).toHaveText(current);

      // Будущая неделя: пустая, но редактируемая.
      await expect(next).toBeEnabled();
      await next.click();
      await expect(label).not.toHaveText(current);
      await expect(page.getByText("На эту неделю пока ничего не запланировано.")).toBeVisible();
      await expect(page.getByRole("button", { name: "+ Добавить упражнение" })).toBeVisible();
      await expectScreenHealthy(page, "Планы: будущая неделя");
      await prev.click();
      await expect(label).toHaveText(current);

      // Копирование недели: подтверждение, «Отмена» ничего не делает, «Скопировать» даёт итог.
      await copyButton.click();
      await expect(page.getByText(/Скопировать свои тренировки и упражнения/)).toBeVisible();
      await page.getByRole("button", { name: "Отмена" }).click();
      await expect(copyButton).toBeVisible();
      await copyButton.click();
      await page.getByRole("button", { name: "Скопировать", exact: true }).click();
      await expect(page.getByTestId("plan-week-copy-result")).toContainText(/Скопировано: \d+, пропущено дублей: \d+/);
      await expect(label).not.toHaveText(current); // после копирования открыта следующая неделя
      await expectScreenHealthy(page, "Планы: после копирования");

      // Перенос на другую неделю: выбор недели есть и ведёт назад.
      await page.getByRole("button", { name: "Перенести" }).first().click();
      await expect(page.getByTestId("move-week-picker")).toBeVisible();
      await expectScreenHealthy(page, "Планы: перенос");
      await pressTelegramBackButton(page);
      await expect(label).toBeVisible();
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
});
