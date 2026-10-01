import { expect, test, type Page } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";
import { pressTelegramBackButton } from "../fixtures/telegramMock";

// Crimpd 8.5.x full-parity contract (docs/CRIMPD_FULL_PARITY_8_5.md).
//
// One focused, growing suite — NOT a copy of the other specs. Every parity issue
// ("CRIMPD P0/P1/P2 — …") adds its own `test.describe("<area>")` block here proving the
// user-visible capability it delivers, at representative mobile widths. The final QA issue
// extends the whole file to light/dark and empty/populated users.
//
// Baseline block below pins what is reachable today, so later blocks can only add surface.
// Read-only user: `ready` (scripts/e2e_seed.py ready 900003).
const READY_USER = 900_003;
const WIDTHS = [320, 390];

async function expectNoHorizontalOverflow(page: Page, where: string) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth, `горизонтальный overflow на «${where}»`).toBeLessThanOrEqual(clientWidth);
}

async function openTab(page: Page, label: string) {
  await page.locator(".bottom-tabbar").getByRole("button", { name: label }).click();
}

for (const width of WIDTHS) {
  test.describe(`Baseline surface @${width}px`, () => {
    test.use({ viewport: { width, height: 760 } });

    test("пять вкладок открываются и показывают основное содержимое", async ({ page }) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, READY_USER);

      // Главная: каталог курсов (G3).
      await expect(page.locator(".plan-title")).toHaveText("Главная");
      await expect(page.locator(".program-card-button").first()).toBeVisible();
      await expectNoHorizontalOverflow(page, "Главная");

      // Планы: «Мои тренировки» как вход в Builder.
      await openTab(page, "Планы");
      await expect(page.getByRole("heading", { name: "Мои тренировки" })).toBeVisible();
      await expectNoHorizontalOverflow(page, "Планы");

      // Журнал и Профиль: экран отрисован, без overflow.
      await openTab(page, "Журнал");
      await expect(page.locator("main, #root").first()).toBeVisible();
      await expectNoHorizontalOverflow(page, "Журнал");

      // Аналитика: переключатель «Тренировки | Программа», по умолчанию «Тренировки».
      await openTab(page, "Аналитика");
      await expect(page.getByRole("tab", { name: "Тренировки", selected: true })).toBeVisible();
      await expectNoHorizontalOverflow(page, "Аналитика");

      await openTab(page, "Профиль");
      await expect(page.locator("main, #root").first()).toBeVisible();
      await expectNoHorizontalOverflow(page, "Профиль");

      expect(consoleErrors).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}

// --- Home (#254): sticky search, category rows, «+» sheet --------------------------------
// Seed: scripts/e2e_seed.py home_discovery (программы в ≥2 категориях + «Другое», свои
// тренировки/упражнения); у светлого и тёмного прогона свой пользователь.
const HOME_USER_LIGHT = 940_001;
const HOME_USER_DARK = 940_002;

for (const width of WIDTHS) {
  for (const [theme, userId] of [["light", HOME_USER_LIGHT], ["dark", HOME_USER_DARK]] as const) {
    test.describe(`Home @${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: 700 } });

      test("sticky поиск, ряды категорий, поиск с фильтром и «+»-шторка", async ({ page }) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, userId, { theme });

        // Ряды по категориям + «Другое».
        const titles = page.getByTestId("program-category-title");
        await expect(titles.first()).toBeVisible();
        expect(await titles.count()).toBeGreaterThanOrEqual(3);
        await expect(titles.filter({ hasText: "e2e_discovery_strength" })).toHaveCount(1);
        await expect(titles.filter({ hasText: "e2e_discovery_mobility" })).toHaveCount(1);
        await expect(titles.last()).toHaveText("Другое");
        await expectNoHorizontalOverflow(page, "Главная");

        // Шапка остаётся видимой при прокрутке.
        const pill = page.getByTestId("home-search-pill");
        await expect(pill).toHaveText("Что потренируем сегодня?");
        await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
        await expect(pill).toBeInViewport();
        await expect(page.getByTestId("home-plus")).toBeInViewport();
        await page.evaluate(() => window.scrollTo(0, 0));

        // «+»: рабочие действия + «Отмена».
        await page.getByTestId("home-plus").click();
        await expect(page.getByRole("button", { name: "Создать тренировку" })).toBeVisible();
        await expect(page.getByRole("button", { name: "Тренировка на сегодня" })).toBeVisible();
        await page.getByRole("button", { name: "Отмена" }).click();
        await expect(page.getByRole("dialog")).toHaveCount(0);
        await page.getByTestId("home-plus").click();
        await page.getByRole("button", { name: "Создать тренировку" }).click();
        await expect(page.getByText("Новая тренировка")).toBeVisible();
        await page.reload();
        await page.getByTestId("home-plus").click();
        await page.getByRole("button", { name: "Тренировка на сегодня" }).click();
        await expect(page.getByTestId("home-search-pill")).toHaveCount(0);
        await openTab(page, "Главная");

        // Поиск: автофокус, счётчик, группы, пустое состояние.
        await page.getByTestId("home-search-pill").click();
        const input = page.getByRole("searchbox", { name: "Поиск" });
        await expect(input).toBeFocused();
        const count = page.getByTestId("search-count");
        await expect(count).toContainText("Найдено:");
        await input.fill("Дискавери");
        await expect(count).toHaveText("Найдено: 3");
        await expect(page.getByTestId("search-result-program")).toHaveCount(3);
        await input.fill("Подтягивания");
        await expect(page.getByTestId("search-result-exercise").first()).toBeVisible();
        await input.fill("Пустая заготовка");
        await expect(page.getByTestId("search-result-workout")).toHaveCount(1);
        await input.fill("такого-нет-zzz");
        await expect(page.getByTestId("search-empty")).toHaveText("Ничего не найдено");
        await expect(count).toHaveText("Найдено: 0");

        // Чипы категорий из реальных данных; сброс возвращает всё.
        await input.fill("");
        const chips = page.getByTestId("search-chips");
        await chips.getByRole("button", { name: "e2e_discovery_mobility" }).click();
        await expect(page.getByTestId("search-result-program")).toHaveCount(1);
        await expect(page.getByTestId("search-result-workout")).toHaveCount(0);
        await expectNoHorizontalOverflow(page, "Поиск");
        await chips.getByRole("button", { name: "Сбросить" }).click();
        await expect(page.getByTestId("search-result-workout").first()).toBeVisible();

        // Результат открывает существующий экран (Program Detail).
        await input.fill("Дискавери: сила");
        await page.getByTestId("search-result-program").click();
        await expect(page.getByRole("button", { name: /Добавить в план/ })).toBeVisible();

        expect(consoleErrors).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("закрытие поиска возвращает на Главную с сохранённой прокруткой", async ({ page }) => {
        await openAppAs(page, userId, { theme });
        await expect(page.getByTestId("program-category-title").first()).toBeVisible();
        await page.evaluate(() => window.scrollTo(0, 200));
        const before = await page.evaluate(() => window.scrollY);
        await page.getByTestId("home-search-pill").click();
        await page.getByRole("button", { name: "Закрыть" }).click();
        await expect(page.getByTestId("home-search-pill")).toBeVisible();
        expect(await page.evaluate(() => window.scrollY)).toBe(before);
      });
    });
  }
}

// --- Workout Detail (#255): read-only карточка своей тренировки ----------------------------
// Seed: scripts/e2e_seed.py workout_detail (читающий пользователь; у «Очень длинной…» две
// завершённые сессии со снимком, у «Пустая заготовка» истории нет, «Планка по времени»
// даёт оценку длительности).
const DETAIL_USER = 950_001;
const LONG_TITLE = /Очень длинная утренняя/;

for (const width of WIDTHS) {
  for (const theme of ["light", "dark"] as const) {
    test.describe(`Workout Detail @${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: 760 } });

      test("карточка с Главной открывает деталь: сводка, упражнения, действия, история", async ({ page }) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, DETAIL_USER, { theme, backButton: true });

        await page.getByTestId("my-workout-card").filter({ hasText: LONG_TITLE }).click();
        await expect(page.getByTestId("workout-detail")).toBeVisible();
        await expect(page.getByTestId("workout-detail-title")).toHaveText(LONG_TITLE);
        await expect(page.getByTestId("workout-detail-subtitle")).toHaveText("Своя тренировка");
        // 3 упражнения на повторения — длительность по полям протокола не посчитать → без оценки.
        await expect(page.getByTestId("workout-detail-meta")).toHaveText("3 упражнения");
        await expect(page.getByTestId("workout-detail-items").locator("li")).toHaveCount(3);
        await expect(page.getByTestId("workout-detail-items")).toContainText("3 × 8 повторений");
        await expect(page.getByRole("button", { name: "Добавить в план" })).toBeVisible();
        await expect(page.getByRole("button", { name: "Редактировать" })).toBeVisible();
        await expect(page.getByTestId("workout-detail-history-row")).toHaveCount(2);
        await expectNoHorizontalOverflow(page, "Workout Detail");

        // «Редактировать» → редактор; назад → снова деталь.
        await page.getByRole("button", { name: "Редактировать" }).click();
        await expect(page.getByTestId("workout-detail")).toHaveCount(0);
        await pressTelegramBackButton(page);
        await expect(page.getByTestId("workout-detail")).toBeVisible();

        // «Добавить в план» → AddToPlanScreen; назад → деталь; назад → Главная.
        await page.getByRole("button", { name: "Добавить в план" }).click();
        await expect(page.getByTestId("workout-detail")).toHaveCount(0);
        await pressTelegramBackButton(page);
        await expect(page.getByTestId("workout-detail")).toBeVisible();
        await pressTelegramBackButton(page);
        await expect(page.getByTestId("my-workouts")).toBeVisible();

        expect(consoleErrors).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("пустая история и оценка длительности; вход из «Мои тренировки»", async ({ page }) => {
        await openAppAs(page, DETAIL_USER, { theme, backButton: true });
        await openTab(page, "Планы");
        await page.getByRole("button", { name: "Мои тренировки" }).click();
        await page.getByRole("button", { name: "Пустая заготовка" }).click();
        await expect(page.getByTestId("workout-detail-title")).toHaveText("Пустая заготовка");
        await expect(page.getByTestId("workout-detail-history-empty")).toHaveText("Вы ещё не выполняли эту тренировку");
        await expect(page.getByTestId("workout-detail-meta")).toHaveText("Пока без упражнений");
        await pressTelegramBackButton(page);

        await page.getByRole("button", { name: "Планка по времени" }).click();
        // 3 × 30 с + 2 × 60 с отдыха = 210 с → ≈ 4 мин.
        await expect(page.getByTestId("workout-detail-meta")).toHaveText("1 упражнение · ≈ 4 мин");
        await expect(page.getByTestId("workout-detail-items")).toContainText("3 × 30 сек · отдых 1:00");
        await expect(page.getByTestId("workout-detail-history-empty")).toBeVisible();
        await expectNoHorizontalOverflow(page, "Workout Detail");
      });
    });
  }
}
