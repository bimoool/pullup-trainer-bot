import { expect, test, type Page } from "@playwright/test";

import { clickAndSync } from "../fixtures/builderFlow";
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

// --- Favorites (#272): сердечко на деталях, ряд «Избранное» на Главной, чип в поиске -------
// Seed: scripts/e2e_seed.py home_discovery 960001..960008 — по пользователю на (ширина, тема,
// сценарий), т.к. избранное сохраняется на сервере и сценарии меняют его состояние.
const FAVORITES_USERS: Record<string, number> = {
  "320-light-flow": 960_001, "320-dark-flow": 960_002, "390-light-flow": 960_003, "390-dark-flow": 960_004,
  "320-light-error": 960_005, "320-dark-error": 960_006, "390-light-error": 960_007, "390-dark-error": 960_008,
};

for (const width of WIDTHS) {
  for (const theme of ["light", "dark"] as const) {
    test.describe(`Favorites @${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: 760 } });

      test("тумблер, сохранение после перезагрузки, ряд на Главной и чип в поиске", async ({ page }) => {
        const { consoleErrors, apiFailures } = await openAppAs(
          page, FAVORITES_USERS[`${width}-${theme}-flow`], { theme, backButton: true },
        );
        const heart = page.getByTestId("favorite-heart");

        // Никогда не добавлял: честная подсказка вместо пустого ряда.
        await expect(page.getByTestId("favorites-hint")).toHaveText("Нажмите ♡ на тренировке, чтобы добавить");

        // Тренировка: мгновенный тумблер.
        await page.getByTestId("my-workout-card").filter({ hasText: LONG_TITLE }).click();
        await expect(heart).toBeEnabled();
        await expect(heart).toHaveAttribute("aria-pressed", "false");
        await heart.click();
        await expect(heart).toHaveAttribute("aria-pressed", "true");
        await expectNoHorizontalOverflow(page, "Workout Detail с ♥");

        // Программа: то же на Program Detail.
        await pressTelegramBackButton(page);
        await page.locator(".program-card-button").filter({ hasText: "Дискавери: сила" }).first().click();
        await expect(heart).toBeEnabled();
        await heart.click();
        await expect(heart).toHaveAttribute("aria-pressed", "true");
        await expectNoHorizontalOverflow(page, "Program Detail с ♥");
        await pressTelegramBackButton(page);

        // Ряд на Главной; переживает перезагрузку; подсказки больше нет.
        const row = page.getByTestId("favorites-row");
        await expect(row.getByTestId("favorite-card")).toHaveCount(2);
        await expect(page.getByTestId("favorites-hint")).toHaveCount(0);
        await page.reload();
        await expect(page.getByTestId("favorites-row").getByTestId("favorite-card")).toHaveCount(2);
        await expectNoHorizontalOverflow(page, "Главная с избранным");

        // Карточка ряда открывает деталь, сердечко уже включено.
        await page.getByTestId("favorites-row").getByTestId("favorite-card").filter({ hasText: LONG_TITLE }).click();
        await expect(page.getByTestId("workout-detail")).toBeVisible();
        await expect(heart).toHaveAttribute("aria-pressed", "true");
        await pressTelegramBackButton(page);

        // Поиск: чип «Избранное» оставляет только избранные программы/тренировки.
        await page.getByTestId("home-search-pill").click();
        const chip = page.getByTestId("search-chip-favorites");
        await expect(chip).toBeVisible();
        await chip.click();
        await expect(page.getByTestId("search-result-program")).toHaveCount(1);
        await expect(page.getByTestId("search-result-workout")).toHaveCount(1);
        await expect(page.getByTestId("search-result-exercise")).toHaveCount(0);
        await expectNoHorizontalOverflow(page, "Поиск «Избранное»");
        await chip.click();
        await expect(page.getByTestId("search-result-exercise").first()).toBeVisible();
        await page.getByRole("button", { name: "Закрыть" }).click();

        // Снять оба: ряд скрывается (подсказка — только тому, кто ни разу не добавлял).
        for (const card of [LONG_TITLE, /Дискавери: сила/]) {
          await page.getByTestId("favorites-row").getByTestId("favorite-card").filter({ hasText: card }).click();
          await expect(heart).toHaveAttribute("aria-pressed", "true");
          await heart.click();
          await expect(heart).toHaveAttribute("aria-pressed", "false");
          await pressTelegramBackButton(page);
        }
        await expect(page.getByTestId("favorites-row")).toHaveCount(0);

        expect(consoleErrors).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("при ошибке запроса сердечко откатывается с короткой ошибкой", async ({ page }) => {
        await openAppAs(page, FAVORITES_USERS[`${width}-${theme}-error`], { theme, backButton: true });
        await page.route("**/api/v2/favorites/**", (route) => route.fulfill({ status: 500, body: "boom" }));
        await page.getByTestId("my-workout-card").filter({ hasText: LONG_TITLE }).click();
        const heart = page.getByTestId("favorite-heart");
        await expect(heart).toBeEnabled();
        await heart.click();
        await expect(page.getByTestId("favorite-error")).toHaveText("Не удалось обновить избранное");
        await expect(heart).toHaveAttribute("aria-pressed", "false");
        await expectNoHorizontalOverflow(page, "Workout Detail с ошибкой");
      });
    });
  }
}

// --- #256 Journal calendar -------------------------------------------------------------
// scripts/e2e_seed.py journal_calendar: предыдущий месяц — сессии 10-го, дважды 15-го и 20-го
// (12:00/18:00 МСК), текущий месяц — одна сессия «только что»; всё остальное пусто.
const MONTHS = [
  "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
  "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
];
const JOURNAL_USERS: Record<number, number> = { 320: 970_001, 390: 970_002 };

function mskMonth(offset: number): { key: string; label: string } {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Moscow", year: "numeric", month: "2-digit" })
    .formatToParts(new Date());
  const year = Number(parts.find((p) => p.type === "year")?.value);
  const month = Number(parts.find((p) => p.type === "month")?.value);
  const index = year * 12 + (month - 1) + offset;
  const y = Math.floor(index / 12);
  const m = (index % 12) + 1;
  return { key: `${y}-${String(m).padStart(2, "0")}`, label: `${MONTHS[m - 1]} ${y}` };
}

for (const width of WIDTHS) {
  for (const theme of ["light", "dark"] as const) {
    test.describe(`Journal calendar @${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: 760 } });

      test("месяц-бар, точки на днях, выбор дня, переключение месяца, пустой месяц", async ({ page }) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, JOURNAL_USERS[width], { theme });
        const requests: string[] = [];
        page.on("request", (request) => requests.push(request.url()));
        await openTab(page, "Журнал");

        const current = mskMonth(0);
        const previous = mskMonth(-1);
        const monthLabel = page.locator(".journal-month-label");
        const cards = page.locator(".history-card-clickable");

        // Месяц-бар сверху, календарь свёрнут; в текущем месяце — одна тренировка.
        await expect(monthLabel).toContainText(current.label);
        await expect(page.locator(".journal-calendar-grid")).toHaveCount(0);
        await expect(cards).toHaveCount(1);
        await expect(page.locator(".journal-week")).toHaveCount(1);
        await expectNoHorizontalOverflow(page, "Журнал: месяц-бар");

        // Тап по подписи раскрывает календарь: Пн первым, точка у сегодняшнего дня.
        await monthLabel.click();
        await expect(page.locator(".journal-calendar-grid")).toBeVisible();
        await expect(page.locator(".journal-calendar-weekday").first()).toHaveText("Пн");
        await expect(page.locator(".journal-calendar-weekday").last()).toHaveText("Вс");
        await expect(page.locator('.journal-calendar-day[data-has-training="true"]')).toHaveCount(1);
        await expect(page.locator(".journal-calendar-today")).toHaveCount(1);
        await expectNoHorizontalOverflow(page, "Журнал: календарь");

        // Предыдущий месяц: точки ровно на 10/15/20; список — 4 карточки, сгруппированные по дням.
        await page.getByRole("button", { name: "Предыдущий месяц" }).click();
        await expect(monthLabel).toContainText(previous.label);
        await expect(cards).toHaveCount(4);
        for (const day of ["10", "15", "20"]) {
          await expect(page.locator(`[data-date="${previous.key}-${day}"][data-has-training="true"]`)).toBeVisible();
        }
        await expect(page.locator(`[data-date="${previous.key}-11"]`)).toHaveAttribute("data-has-training", "false");
        await expect(page.locator('.journal-calendar-day[data-has-training="true"]')).toHaveCount(3);
        await expect(page.locator(".journal-day")).toHaveCount(3);
        await expect(page.locator(".journal-week-header").first()).toBeVisible();
        await expect(page.locator(".journal-day-header").first()).toContainText(/\d/);
        await expectNoHorizontalOverflow(page, "Журнал: прошлый месяц");

        // Выбор дня фильтрует список запросом с диапазоном дня; повторный тап снимает выбор.
        const day15 = page.locator(`.journal-calendar-day[data-date="${previous.key}-15"]`);
        await day15.click();
        await expect(day15).toHaveAttribute("aria-pressed", "true");
        await expect(cards).toHaveCount(2);
        await expect(page.locator(".journal-day")).toHaveCount(1);
        expect(requests.some((url) => url.includes(`date_from=${previous.key}-15&date_to=${previous.key}-15`))).toBe(true);
        await day15.click();
        await expect(day15).toHaveAttribute("aria-pressed", "false");
        await expect(cards).toHaveCount(4);

        // День без тренировок — пустое состояние; смена месяца сбрасывает выбор.
        await page.locator(`.journal-calendar-day[data-date="${previous.key}-11"]`).click();
        await expect(page.getByText("В этот день тренировок нет")).toBeVisible();
        await page.getByRole("button", { name: "Предыдущий месяц" }).click();
        await expect(monthLabel).toContainText(mskMonth(-2).label);
        await expect(page.getByText("В этом месяце тренировок нет")).toBeVisible();
        await expect(cards).toHaveCount(0);
        await expectNoHorizontalOverflow(page, "Журнал: пустой месяц");

        // Назад к текущему месяцу двумя «›»; данные запрашиваются по месяцам, а не всей историей.
        const next = page.getByRole("button", { name: "Следующий месяц" });
        await next.click();
        await next.click();
        await expect(monthLabel).toContainText(current.label);
        await expect(cards).toHaveCount(1);
        expect(requests.filter((url) => url.includes("/api/v2/sessions?")).every((url) => url.includes("date_from="))).toBe(true);

        expect(consoleErrors).toEqual([]);
        expect(apiFailures).toEqual([]);
      });
    });
  }
}

// --- Live effort (#257): подписанные чипы усилия, review-шаг, значения в Журнале ------------
// Seed: scripts/e2e_seed.py golden_journey (своя Workout «Золотая тренировка», reps 2 x 8);
// по пользователю на ширину/тему и на попытку retry (retry делит БД с первой попыткой).
const EFFORT_TITLE = "Золотая тренировка";
const EFFORT_USERS = { 320: { id: 980_001, theme: "light" }, 390: { id: 980_011, theme: "dark" } } as const;

for (const width of WIDTHS) {
  const { id, theme } = EFFORT_USERS[width as 320 | 390];
  test.describe(`Live effort @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 760 } });
    test.setTimeout(120_000);

    test("чипы со словами, review-шаг «Как прошла тренировка?», оценка и заметка в Журнале", async ({ page }, testInfo) => {
      page.on("dialog", (dialog) => void dialog.accept());
      const { consoleErrors, apiFailures } = await openAppAs(page, id + testInfo.retry, { theme });
      const completeBodies: unknown[] = [];
      page.on("request", (request) => {
        if (request.method() === "POST" && request.url().includes("/complete")) {
          completeBodies.push(request.postDataJSON());
        }
      });

      // В план → старт.
      await page.getByTestId("my-workout-card").filter({ hasText: EFFORT_TITLE }).click();
      await page.getByRole("button", { name: "Добавить в план" }).click();
      await page.getByRole("button", { name: "Свободный пул" }).click();
      await page.getByRole("button", { name: "Добавить", exact: true }).click();
      const group = page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${EFFORT_TITLE}`) });
      await group.getByRole("button", { name: "Начать", exact: true }).click();
      await page.getByRole("button", { name: "Начать", exact: true }).click();
      await expect(page.getByText("Живая тренировка")).toBeVisible();

      // Подход 1: вопрос и подписанные чипы 1–5.
      await clickAndSync(page, "Готов", "/phase/next");
      await expect(page.getByText("Насколько тяжело было?")).toBeVisible();
      const chips = page.getByTestId("set-effort").getByRole("button");
      await expect(chips).toHaveCount(5);
      const words = ["Очень легко", "Легко", "Средне", "Тяжело", "Предел"];
      for (let i = 0; i < 5; i += 1) {
        await expect(chips.nth(i)).toContainText(String(i + 1));
        await expect(chips.nth(i)).toContainText(words[i]);
      }
      await expectNoHorizontalOverflow(page, "Live: чипы усилия");
      await page.getByLabel(/Результат|Секунды|Повторений/).fill("8");
      await chips.nth(3).click(); // «Тяжело» — сохраняется как 4
      await expect(chips.nth(3)).toHaveAttribute("aria-pressed", "true");
      await clickAndSync(page, "Готово", "/sets:batch");
      await clickAndSync(page, "Пропустить отдых", "/phase/next");
      await clickAndSync(page, "Готов", "/phase/next");
      await page.getByLabel(/Результат|Секунды|Повторений/).fill("7");
      await clickAndSync(page, "Готово", "/sets:batch");

      // Review-шаг: открывается по «Завершить», «Назад» возвращает, оценка необязательна.
      await page.getByRole("button", { name: "Завершить", exact: true }).click();
      const review = page.getByTestId("workout-review");
      await expect(review).toContainText("Как прошла тренировка?");
      await expect(review.getByTestId("workout-effort").getByRole("button")).toHaveCount(5);
      await expect(review.getByLabel("Заметка к тренировке")).toBeVisible();
      await expectNoHorizontalOverflow(page, "Live: review-шаг");
      await review.getByRole("button", { name: "Назад", exact: true }).click();
      await expect(review).toHaveCount(0);
      await page.getByRole("button", { name: "Завершить", exact: true }).click();
      expect(completeBodies).toEqual([]); // без «Сохранить и завершить» ничего не завершено

      await review.getByTestId("workout-effort").getByRole("button").nth(4).click(); // «Предел»
      await review.getByLabel("Заметка к тренировке").fill("Хорошо потянул, локоть тянет");
      await clickAndSync(page, "Сохранить и завершить", "/complete");
      await expect(page.getByText("Тренировка завершена")).toBeVisible();
      expect(completeBodies).toEqual([
        { abandoned: false, effort: "5", comment: "Хорошо потянул, локоть тянет" },
      ]);
      await page.getByRole("button", { name: "Закрыть" }).click();

      // Журнал: оценка тренировки со словом, заметка, усилие подхода.
      await openTab(page, "Журнал");
      await page.locator(".history-card").filter({ hasText: EFFORT_TITLE }).click();
      await expect(page.getByTestId("journal-workout-effort")).toContainText("5 Предел");
      await expect(page.getByTestId("journal-workout-comment")).toContainText("Хорошо потянул, локоть тянет");
      await expect(page.getByText(/усилие 4 Тяжело/)).toBeVisible();
      await expectNoHorizontalOverflow(page, "Журнал: детали с оценкой");

      expect(consoleErrors.filter((e) => !e.includes("Wake Lock"))).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
