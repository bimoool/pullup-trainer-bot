import { expect, test, type Page } from "@playwright/test";

import { clickAndSync, noWakeLock } from "../fixtures/builderFlow";
import { openJournalEntry } from "../fixtures/parity";
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
      await expect(
        page.getByRole("tablist", { name: "Раздел аналитики" }).getByRole("tab", { name: "Тренировки", selected: true }),
      ).toBeVisible();
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
      // #265: во время работы панель свёрнута — оценка и заметка раскрываются вручную.
      await expect(page.getByText("Насколько тяжело было?")).toHaveCount(0);
      await page.getByTestId("log-panel-toggle").click();
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
      await openJournalEntry(page, page.locator(".history-card").filter({ hasText: EFFORT_TITLE }));
      await expect(page.getByTestId("journal-workout-effort")).toContainText("5 Предел");
      await expect(page.getByTestId("journal-workout-comment")).toContainText("Хорошо потянул, локоть тянет");
      await expect(page.getByText(/усилие 4 Тяжело/)).toBeVisible();
      await expectNoHorizontalOverflow(page, "Журнал: детали с оценкой");

      expect(consoleErrors.filter((e) => !e.includes("Wake Lock"))).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}

// --- Plans week (#258): степпер недели, счётчики «сделано/план», read-only прошлые недели --------
// Seed: scripts/e2e_seed.py plan_week_stepper — прошлая неделя («Планка» 1/1) и текущая
// («Планка» 1/2, «Отжимания» 0/1); только чтение, поэтому retry безопасен.
const PLANS_WEEK_USERS = { 320: { id: 990_001, theme: "light" }, 390: { id: 990_002, theme: "dark" } } as const;

for (const width of WIDTHS) {
  const { id, theme } = PLANS_WEEK_USERS[width as 320 | 390];
  test.describe(`Plans week @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 760 } });

    test("степпер недели, счётчики, прогресс «N из M», прошлая неделя read-only", async ({ page }) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, id, { theme });
      await openTab(page, "Планы");

      const label = page.getByTestId("plan-week-label");
      const progress = page.getByTestId("plan-week-progress");
      const counters = page.getByTestId("plan-item-counter");
      const prev = page.getByRole("button", { name: "Предыдущая неделя" });
      const next = page.getByRole("button", { name: "Следующая неделя" });

      // По умолчанию — текущая неделя, ровно одна; › доступна (#275: создаёт будущую неделю).
      await expect(label).toHaveCount(1);
      await expect(label).toContainText(/Неделя \d+ · \d{1,2} \S+ – \d{1,2} \S+/);
      await expect(page.getByTestId("plan-week-stepper")).toContainText("База");
      await expect(next).toBeEnabled();
      await expect(prev).toBeEnabled();
      await expect(progress).toContainText("Текущая неделя · 1 из 3");
      await expect(counters).toHaveText(["1/2", "0/1"]);
      await expect(page.getByRole("button", { name: "Начать", exact: true })).toHaveCount(2);
      await expect(page.getByRole("button", { name: "+ Добавить упражнение" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Перенести" })).toHaveCount(2);
      await expectNoHorizontalOverflow(page, "Plans week: текущая");
      const currentLabel = await label.textContent();

      // ‹ — прошлая неделя: свои дата и счётчик, действия текущей недели скрыты.
      await prev.click();
      await expect(label).not.toHaveText(currentLabel ?? "");
      await expect(progress).toHaveText("1 из 1");
      await expect(counters).toHaveText(["1/1"]);
      await expect(page.getByRole("button", { name: "Начать", exact: true })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "+ Добавить упражнение" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Перенести" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Убрать из плана" })).toHaveCount(0);
      await expect(next).toBeEnabled();
      await expectNoHorizontalOverflow(page, "Plans week: прошлая");

      // › возвращает на текущую.
      await next.click();
      await expect(label).toHaveText(currentLabel ?? "");
      await expect(next).toBeEnabled();

      expect(consoleErrors).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}

// --- Analytics metric (#259): «Тренировки | Минуты», период 1 мес / 3 мес / Свой, недельные столбики ---
// Seed: scripts/e2e_seed.py analytics_metric — 3 и 5 дней назад по 40 и 30 мин, 6 дней назад без
// времени, 50 дней назад 60 мин. 1 мес: 3 тренировки / 70 мин / 1 без времени; 3 мес: 4 / 130 / 1.
// Только чтение — retry безопасен.
const METRIC_USERS = { 320: { id: 995_001, theme: "light" }, 390: { id: 995_002, theme: "dark" } } as const;

function mskDaysAgo(days: number): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Moscow", year: "numeric", month: "2-digit", day: "2-digit" })
    .format(new Date(Date.now() - days * 86_400_000));
}

/** Значения столбиков из aria-label графика: «… (с понедельника): 28.09: 2, 05.10: 0». */
async function chartValues(page: Page): Promise<number[]> {
  const label = (await page.locator(".analytics-weeks-chart").getAttribute("aria-label")) ?? "";
  return label.split("): ")[1].split(", ").map((entry) => Number(entry.split(": ")[1]));
}

for (const width of WIDTHS) {
  const { id, theme } = METRIC_USERS[width as 320 | 390];
  test.describe(`Analytics metric @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 800 } });

    test("по умолчанию 1 мес / Тренировки; переключение метрики, периода и «Свой»", async ({ page }) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, id, { theme });
      await openTab(page, "Аналитика");
      const card = page.getByTestId("analytics-metrics");
      const metricTab = (name: string) => card.getByRole("tablist", { name: "Метрика" }).getByRole("tab", { name });
      const rangeTab = (name: string) => card.getByRole("tablist", { name: "Период" }).getByRole("tab", { name });
      const total = page.getByTestId("analytics-metric-total");

      // Значения по умолчанию.
      await expect(metricTab("Тренировки")).toHaveAttribute("aria-selected", "true");
      await expect(rangeTab("1 мес")).toHaveAttribute("aria-selected", "true");
      await expect(page.locator(".analytics-weeks-chart")).toHaveAttribute("data-metric", "workouts");
      await expect(total).toContainText("Всего тренировок: 3");
      expect((await chartValues(page)).reduce((a, b) => a + b, 0)).toBe(3);
      await expect(page.getByTestId("analytics-no-duration")).toHaveCount(0); // только в «Минуты»
      await expect(page.getByTestId("analytics-custom-range")).toHaveCount(0);
      await expectNoHorizontalOverflow(page, "Аналитика: 1 мес / Тренировки");

      // Минуты: сумма по неделям = 70, тренировка без времени не в минутах, но названа.
      await metricTab("Минуты").click();
      await expect(page.locator(".analytics-weeks-chart")).toHaveAttribute("data-metric", "minutes");
      expect((await chartValues(page)).reduce((a, b) => a + b, 0)).toBe(70);
      await expect(total).toContainText("Всего минут: 1 ч 10 мин");
      await expect(page.getByTestId("analytics-no-duration")).toHaveText("без данных о времени: 1");
      await expectNoHorizontalOverflow(page, "Аналитика: Минуты");

      // (i): определения обеих метрик, закрывается.
      await card.getByRole("button", { name: "Что значат метрики" }).click();
      const sheet = page.getByRole("dialog", { name: "Что значат метрики" });
      await expect(sheet).toContainText("Тренировки — сколько завершённых");
      await expect(sheet).toContainText("Минуты — сумма длительностей");
      await expect(sheet).toContainText("от 1 минуты до 6 часов");
      await expectNoHorizontalOverflow(page, "Аналитика: шторка определений");
      await sheet.getByRole("button", { name: "Закрыть" }).click();
      await expect(sheet).toHaveCount(0);

      // 3 мес: запрос с from/to; недели начинаются с понедельника; 130 мин, 4 тренировки.
      const response = page.waitForResponse((r) => r.url().includes("/api/v2/analytics/training?from="));
      await rangeTab("3 мес").click();
      const body = await (await response).json();
      expect(body.metrics.weeks.length).toBeGreaterThanOrEqual(13);
      for (const week of body.metrics.weeks as { week_start: string }[]) {
        expect(new Date(`${week.week_start}T00:00:00Z`).getUTCDay()).toBe(1);
      }
      await expect(total).toContainText("Всего минут: 2 ч 10 мин");
      await expect(page.getByTestId("analytics-no-duration")).toHaveText("без данных о времени: 1");
      await metricTab("Тренировки").click();
      await expect(total).toContainText("Всего тренировок: 4");
      await expectNoHorizontalOverflow(page, "Аналитика: 3 мес");

      // Свой: даты + «Применить»; перевёрнутый диапазон не применяется.
      await rangeTab("Свой").click();
      const custom = page.getByTestId("analytics-custom-range");
      const apply = custom.getByRole("button", { name: "Применить" });
      await expectNoHorizontalOverflow(page, "Аналитика: Свой");
      await custom.getByLabel("С", { exact: true }).fill(mskDaysAgo(51));
      await custom.getByLabel("По", { exact: true }).fill(mskDaysAgo(49));
      await expect(apply).toBeEnabled();
      await custom.getByLabel("С", { exact: true }).fill(mskDaysAgo(40)); // позже «По»
      await expect(apply).toBeDisabled();
      await expect(custom).toContainText("Начало позже конца");
      await custom.getByLabel("С", { exact: true }).fill(mskDaysAgo(51));
      await apply.click();
      await expect(total).toContainText("Всего тренировок: 1");
      await metricTab("Минуты").click();
      await expect(total).toContainText("Всего минут: 1 ч");
      await expect(page.getByTestId("analytics-no-duration")).toHaveCount(0); // у этой тренировки время есть

      // Назад на «1 мес» — снова 70 минут.
      await rangeTab("1 мес").click();
      await expect(total).toContainText("Всего минут: 1 ч 10 мин");

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}

// --- Tests (#260): хаб «Тесты» — карточки, тренд, запись/правка/удаление результата ---------------
// Seed: scripts/e2e_seed.py tests_hub — «Максимум подтягиваний»: 10 повт. (20 дней назад) и 12 повт.
// (5 дней назад); «Вис на перекладине, сек» и «Подтягивания с весом, кг» без результатов.
// Тест сам пишет и удаляет результаты «Вис…»; по пользователю на ширину/тему и на retry.
const TESTS_USERS = { 320: { id: 996_001, theme: "light" }, 390: { id: 996_002, theme: "dark" } } as const;
const HANG_NAME = "Вис на перекладине, сек";
const PULLUPS_NAME = "Максимум подтягиваний";

function ruDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-");
  return `${day}.${month}.${year}`;
}

for (const width of WIDTHS) {
  const { id, theme } = TESTS_USERS[width as 320 | 390];
  test.describe(`Tests @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 800 } });

    test("карточки с Главной и Профиля; запись, график, правка и удаление результата", async ({ page }, testInfo) => {
      const dialogs: string[] = [];
      page.on("dialog", (dialog) => {
        dialogs.push(dialog.message());
        void dialog.accept();
      });
      const { consoleErrors, apiFailures } = await openAppAs(page, id + testInfo.retry * 10, { theme, backButton: true });
      const card = (name: string) => page.getByTestId("test-card").filter({ hasText: name });
      const rows = page.getByTestId("test-history-row");

      // Главная: строка «Тесты» ведёт в хаб; три карточки, у проходивших тест — результат и тренд.
      await page.getByTestId("home-tests-row").click();
      await expect(page.getByTestId("test-card")).toHaveCount(3);
      await expect(card(PULLUPS_NAME).getByTestId("test-card-last")).toHaveText(`12 повт. · ${ruDate(mskDaysAgo(5))}`);
      await expect(card(PULLUPS_NAME).getByTestId("test-card-trend")).toBeVisible();
      await expect(card(HANG_NAME).getByTestId("test-card-last")).toHaveText("Ещё не проходили");
      await expect(card(HANG_NAME).getByTestId("test-card-trend")).toHaveCount(0);
      await expectNoHorizontalOverflow(page, "Тесты: список");

      // Деталь теста без результатов: описание, пояснение про прогрессию, пустая история и график.
      await card(HANG_NAME).click();
      await expect(page.getByTestId("test-detail-title")).toHaveText(HANG_NAME);
      await expect(page.getByTestId("test-detail-description")).not.toBeEmpty();
      await expect(page.getByTestId("test-detail-note")).toContainText("не влияют на прогрессию");
      await expect(page.getByTestId("test-history-empty")).toBeVisible();
      await expect(page.getByTestId("test-chart-empty")).toBeVisible();
      await expectNoHorizontalOverflow(page, "Тест: пустая деталь");

      // Валидация формы: нулевое значение не уходит на сервер.
      const form = page.getByTestId("test-form");
      await form.getByLabel("Результат, сек").fill("0");
      await form.getByRole("button", { name: "Записать результат" }).click();
      await expect(page.getByTestId("test-form-error")).toHaveText("Введите значение больше нуля");
      await expect(rows).toHaveCount(0);

      // Запись двух результатов: сегодня и два дня назад; новые первыми, график появляется со второго.
      await form.getByLabel("Результат, сек").fill("42,5");
      await form.getByLabel("Заметка (необязательно)").fill("с резиной");
      await form.getByRole("button", { name: "Записать результат" }).click();
      await expect(rows).toHaveCount(1);
      await expect(rows.first()).toContainText("42.5 сек");
      await expect(rows.first()).toContainText("с резиной");
      await expect(page.getByTestId("test-chart-empty")).toBeVisible();
      await form.getByLabel("Дата").fill(mskDaysAgo(2));
      await form.getByLabel("Результат, сек").fill("50");
      await form.getByRole("button", { name: "Записать результат" }).click();
      await expect(rows).toHaveCount(2);
      await expect(rows.nth(0)).toContainText("42.5 сек");
      await expect(rows.nth(1)).toContainText("50 сек");
      await expect(rows.nth(1)).toContainText(ruDate(mskDaysAgo(2)));
      await expect(page.getByTestId("test-chart")).toHaveAttribute("data-points", "2");
      await expectNoHorizontalOverflow(page, "Тест: история и график");

      // Правка: значение меняется, форма возвращается к записи.
      await rows.nth(0).getByRole("button", { name: /^Изменить/ }).click();
      await expect(form).toContainText("Изменить результат");
      await form.getByLabel("Результат, сек").fill("45");
      await form.getByRole("button", { name: "Сохранить" }).click();
      await expect(rows.nth(0)).toContainText("45 сек");
      await expect(form).toContainText("Записать результат");

      // Список показывает последний результат и тренд.
      await pressTelegramBackButton(page);
      await expect(card(HANG_NAME).getByTestId("test-card-trend")).toBeVisible();
      await expect(card(HANG_NAME).getByTestId("test-card-last")).toContainText("45 сек · ");

      // Удаление с подтверждением: оба результата, график исчезает.
      await card(HANG_NAME).click();
      await rows.nth(0).getByRole("button", { name: /^Удалить/ }).click();
      await expect(rows).toHaveCount(1);
      await expect(page.getByTestId("test-chart-empty")).toBeVisible();
      await rows.nth(0).getByRole("button", { name: /^Удалить/ }).click();
      await expect(page.getByTestId("test-history-empty")).toBeVisible();
      expect(dialogs).toHaveLength(2);
      expect(dialogs[0]).toContain("Удалить результат 45 сек");

      // Профиль: тот же список в карточке «Тесты»; деталь с историей и графиком.
      await openTab(page, "Профиль");
      const profileTests = page.getByTestId("profile-tests");
      await expect(profileTests.getByTestId("test-card")).toHaveCount(3);
      await expect(profileTests.getByTestId("test-card").filter({ hasText: HANG_NAME }).getByTestId("test-card-last"))
        .toHaveText("Ещё не проходили");
      await profileTests.getByTestId("test-card").filter({ hasText: PULLUPS_NAME }).click();
      await expect(rows).toHaveCount(2);
      await expect(rows.first()).toContainText("12 повт.");
      await expect(page.getByTestId("test-chart")).toBeVisible();
      await expectNoHorizontalOverflow(page, "Профиль → деталь теста");

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}

// --- Workout delete/duplicate (#261): «Дублировать» и «Удалить тренировку» в редакторе ----
// Seed: scripts/e2e_seed.py workout_detail 997101..997104 — по пользователю на (ширина, тема),
// т.к. сценарий меняет состав тренировок на сервере. «Очень длинная…» имеет 2 завершённые
// сессии со снимком — после удаления они остаются, а сама тренировка пропадает из списков.
const DELETE_DUPLICATE_USERS: Record<string, number> = {
  "320-light": 997_101, "320-dark": 997_102, "390-light": 997_103, "390-dark": 997_104,
};

for (const width of WIDTHS) {
  for (const theme of ["light", "dark"] as const) {
    test.describe(`Workout delete/duplicate @${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: 760 } });

      test("дублирование появляется сразу; удаление с подтверждением убирает из Главной, списка и поиска", async ({ page }) => {
        const userId = DELETE_DUPLICATE_USERS[`${width}-${theme}`];
        const { consoleErrors, apiFailures } = await openAppAs(page, userId, { theme, backButton: true });
        const cards = page.getByTestId("my-workout-card");

        // Дублировать: редактор → «Дублировать» → на Главной сразу появляется «… (копия)».
        await cards.filter({ hasText: LONG_TITLE }).first().click();
        await page.getByRole("button", { name: "Редактировать" }).click();
        await expect(page.getByRole("button", { name: "Дублировать" })).toBeVisible();
        await expectNoHorizontalOverflow(page, "Редактор с «Дублировать» и «Удалить»");
        await page.getByRole("button", { name: "Дублировать" }).click();
        await expect(page.getByTestId("my-workouts")).toBeVisible();
        const copy = cards.filter({ hasText: "(копия)" });
        await expect(copy).toHaveCount(1);
        await copy.click();
        await expect(page.getByTestId("workout-detail-title")).toContainText("(копия)");
        await expect(page.getByTestId("workout-detail-items").locator("li")).toHaveCount(3);
        await pressTelegramBackButton(page);

        // Удалить копию: сначала подтверждение с текстом, «Отмена» ничего не удаляет.
        await copy.click();
        await page.getByRole("button", { name: "Редактировать" }).click();
        await page.getByRole("button", { name: "Удалить тренировку" }).click();
        await expect(page.getByTestId("workout-delete")).toContainText(
          "Удалить тренировку? Это не удалит уже выполненные тренировки из журнала.",
        );
        await expectNoHorizontalOverflow(page, "Подтверждение удаления тренировки");
        await page.getByTestId("workout-delete").getByRole("button", { name: "Отмена" }).click();
        await expect(page.getByRole("button", { name: "Удалить тренировку" })).toBeVisible();
        await page.getByRole("button", { name: "Удалить тренировку" }).click();
        await page.getByRole("button", { name: "Да, удалить" }).click();
        await expect(page.getByTestId("my-workouts")).toBeVisible();
        await expect(cards.filter({ hasText: "(копия)" })).toHaveCount(0);
        await expect(cards.filter({ hasText: LONG_TITLE })).toHaveCount(1);

        // Удалить оригинал: исчезает с Главной и из поиска, после перезагрузки тоже.
        await cards.filter({ hasText: LONG_TITLE }).click();
        await page.getByRole("button", { name: "Редактировать" }).click();
        await page.getByRole("button", { name: "Удалить тренировку" }).click();
        await page.getByRole("button", { name: "Да, удалить" }).click();
        await expect(page.getByTestId("my-workouts")).toBeVisible();
        await expect(cards.filter({ hasText: LONG_TITLE })).toHaveCount(0);

        await page.getByTestId("home-search-pill").click();
        await page.getByRole("searchbox", { name: "Поиск" }).fill("Очень длинная");
        await expect(page.getByTestId("search-result-workout")).toHaveCount(0);

        await openAppAs(page, userId, { theme, backButton: true });
        await expect(cards.filter({ hasText: LONG_TITLE })).toHaveCount(0);
        await expect(cards.filter({ hasText: "Пустая заготовка" })).toHaveCount(1);

        expect(noWakeLock(consoleErrors)).toEqual([]);
        expect(apiFailures).toEqual([]);
      });
    });
  }
}

// --- Journal edit/clone (#262): «Изменить» и «Повторить (клонировать)» в деталях записи ------
// Seed: scripts/e2e_seed.py journal_edit 997201/997202 (по пользователю на ширину; сценарий
// меняет данные). Две сегодняшние записи (МСК): Builder «Моя силовая» со снимком (can_edit) и
// историческая без снимка («Тренировка» — править/клонировать нельзя, кнопок нет).
const JOURNAL_EDIT_USERS: Record<number, number> = { 320: 997_201, 390: 997_202 };

function mskDay(offsetDays: number): string {
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Moscow" }).format(new Date());
  const [y, m, d] = today.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + offsetDays)).toISOString().slice(0, 10);
}

for (const width of WIDTHS) {
  test.describe(`Journal edit/clone @${width}px`, () => {
    test.use({ viewport: { width, height: 760 } });

    test("кнопки только у безопасной записи; правка значений/усилия/заметок/даты; клон на сегодня", async ({ page }) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, JOURNAL_EDIT_USERS[width], { backButton: true });
      await openTab(page, "Журнал");
      const cards = page.locator(".history-card-clickable");
      await expect(cards).toHaveCount(2);
      const mine = cards.filter({ hasText: "Моя силовая" });
      const historical = cards.filter({ hasText: "Тренировка" }).filter({ hasNotText: "Моя силовая" });

      // Историческая запись без снимка: сервер не доказал безопасность — ни «Изменить», ни «Повторить».
      // Шторка (#280) честно показывает то же: только «Открыть» (и «Отмена»), без правки/клона/удаления.
      await historical.click();
      await expect(page.getByTestId("journal-entry-sheet")).toBeVisible();
      await expect(page.getByTestId("journal-sheet-edit")).toHaveCount(0);
      await expect(page.getByTestId("journal-sheet-clone")).toHaveCount(0);
      await expect(page.getByTestId("journal-sheet-delete")).toHaveCount(0);
      await page.getByTestId("journal-sheet-open").click();
      await expect(page.getByRole("button", { name: /Изменить/ })).toHaveCount(0);
      await expect(page.getByRole("button", { name: /Повторить/ })).toHaveCount(0);
      await expect(page.getByRole("button", { name: /Удалить/ })).toHaveCount(0);
      await pressTelegramBackButton(page);

      // Builder-запись: рядом с «Удалить» появились обе кнопки.
      await openJournalEntry(page, mine);
      await expect(page.getByRole("button", { name: /Изменить/ })).toBeVisible();
      await expect(page.getByRole("button", { name: /Повторить \(клонировать\)/ })).toBeVisible();
      await expect(page.getByRole("button", { name: /Удалить/ })).toBeVisible();
      await expectNoHorizontalOverflow(page, "Журнал: детали с кнопками");

      // Форма правки: текущие значения подставлены; будущая дата отклоняется на клиенте.
      await page.getByRole("button", { name: /Изменить/ }).click();
      const form = page.getByTestId("journal-edit-form");
      await expect(form).toBeVisible();
      await expect(form.getByLabel("Подход 1: значение")).toHaveValue("8");
      await expect(form.getByLabel("Подход 2: значение")).toHaveValue("7");
      await expect(form.getByLabel("Подход 2: заметка")).toHaveValue("Последние тяжело");
      await expectNoHorizontalOverflow(page, "Журнал: форма правки");

      await form.getByLabel("Дата тренировки").fill(mskDay(1));
      await form.getByRole("button", { name: "Сохранить" }).click();
      await expect(form.getByRole("alert")).toContainText("в будущем");

      const yesterday = mskDay(-1);
      await form.getByLabel("Дата тренировки").fill(yesterday);
      await form.getByLabel("Подход 1: значение").fill("12");
      await form.getByLabel("Подход 1: усилие").selectOption({ label: "5 Предел" });
      await form.getByLabel("Подход 1: заметка").fill("рывком");
      await form.getByLabel("Усилие тренировки").selectOption({ label: "4 Тяжело" });
      await form.getByLabel("Комментарий к тренировке").fill("Изменено в журнале");
      await form.getByRole("button", { name: "Сохранить" }).click();

      // Возврат в Журнал; запись переехала на вчера — при необходимости идём в её месяц.
      await expect(page.getByTestId("journal-edit-form")).toHaveCount(0);
      const todayMonth = mskDay(0).slice(0, 7);
      if (yesterday.slice(0, 7) !== todayMonth) {
        await page.getByRole("button", { name: "Предыдущий месяц" }).click();
      }
      await expect(mine).toHaveCount(1);
      await openJournalEntry(page, mine);
      await expect(page.getByTestId("journal-workout-effort")).toContainText("4 Тяжело");
      await expect(page.getByTestId("journal-workout-comment")).toContainText("Изменено в журнале");
      await expect(page.getByText("Подход 1 · усилие 5 Предел · рывком")).toBeVisible();
      await expect(page.getByText(/Факт: 12/)).toBeVisible();

      // Клон: дата по умолчанию — сегодня; создаётся вторая «Моя силовая» с теми же результатами.
      // Кнопка деталей «Повторить (клонировать)» остаётся; сам клон — из шторки записи (#280).
      await expect(page.getByRole("button", { name: /Повторить \(клонировать\)/ })).toBeVisible();
      await pressTelegramBackButton(page);
      await openJournalEntry(page, mine, "clone");
      const cloneForm = page.getByTestId("journal-clone-form");
      await expect(cloneForm.getByLabel("Дата новой записи")).toHaveValue(mskDay(0));
      await expectNoHorizontalOverflow(page, "Журнал: форма клона");
      await cloneForm.getByRole("button", { name: "Создать копию" }).click();
      await expect(page.getByTestId("journal-clone-form")).toHaveCount(0);
      await expect(page.locator(".journal-month-label")).toBeVisible();
      if (yesterday.slice(0, 7) !== todayMonth) {
        await expect(page.locator(".journal-month-label")).toContainText(/\d{4}/);
      }
      await expect(cards.filter({ hasText: "Моя силовая" })).toHaveCount(
        yesterday.slice(0, 7) !== todayMonth ? 1 : 2,
      );
      await expectNoHorizontalOverflow(page, "Журнал: после клона");

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}

// --- Live extra set & pause (#264): «+ Ещё подход» после плана, пауза отсчёта ----------------
// Seed: golden_journey (reps 2 x 8) — своя пара пользователей на ширину/тему и на retry.
const PAUSE_USERS = { 320: { id: 980_021, theme: "light" }, 390: { id: 980_031, theme: "dark" } } as const;

for (const width of WIDTHS) {
  const { id, theme } = PAUSE_USERS[width as 320 | 390];
  test.describe(`Live extra set & pause @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 760 } });
    test.setTimeout(120_000);

    test("пауза замораживает отдых и переживает reload; «+ Ещё подход» после плана уходит как is_extra", async ({ page }, testInfo) => {
      page.on("dialog", (dialog) => void dialog.accept());
      const { consoleErrors, apiFailures } = await openAppAs(page, id + testInfo.retry, { theme });
      const batchBodies: { sets: { is_extra?: boolean; value: string }[] }[] = [];
      page.on("request", (request) => {
        if (request.method() === "POST" && request.url().includes("/sets:batch")) {
          batchBodies.push(request.postDataJSON());
        }
      });

      await page.getByTestId("my-workout-card").filter({ hasText: EFFORT_TITLE }).click();
      await page.getByRole("button", { name: "Добавить в план" }).click();
      await page.getByRole("button", { name: "Свободный пул" }).click();
      await page.getByRole("button", { name: "Добавить", exact: true }).click();
      const group = page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${EFFORT_TITLE}`) });
      await group.getByRole("button", { name: "Начать", exact: true }).click();
      await page.getByRole("button", { name: "Начать", exact: true }).click();
      await expect(page.getByText("Живая тренировка")).toBeVisible();

      // Пауза не предлагается в фазе «Пошёл»; «+ Ещё подход» — пока план не выполнен.
      await clickAndSync(page, "Готов", "/phase/next");
      await expect(page.getByText("Пошёл")).toBeVisible();
      await expect(page.getByTestId("pause-toggle")).toHaveCount(0);
      await expect(page.getByTestId("extra-set-button")).toHaveCount(0);
      await page.getByLabel(/Результат|Секунды|Повторений/).fill("8");
      await clickAndSync(page, "Готово", "/sets:batch");

      // Отдых: пауза → таймер стоит, «Продолжить»; reload — пауза сохранена.
      await expect(page.getByRole("heading", { name: "Отдых", exact: true })).toBeVisible();
      const timer = page.locator(".timer-duration-label");
      await page.getByTestId("pause-toggle").click();
      await expect(page.getByTestId("pause-toggle")).toHaveText("Продолжить");
      const frozen = await timer.innerText();
      await page.waitForTimeout(2300);
      expect(await timer.innerText()).toBe(frozen);
      await expectNoHorizontalOverflow(page, "Live: пауза");

      await page.reload();
      await expect(page.getByText("Живая тренировка")).toBeVisible();
      await expect(page.getByTestId("pause-toggle")).toHaveText("Продолжить");
      expect(await timer.innerText()).toBe(frozen);

      // Продолжить — отсчёт идёт дальше с остатка.
      await page.getByTestId("pause-toggle").click();
      await expect(page.getByTestId("pause-toggle")).toHaveText("Пауза");
      await expect.poll(async () => timer.innerText(), { timeout: 5000 }).not.toBe(frozen);

      // Второй (последний плановый) подход, затем «+ Ещё подход».
      await clickAndSync(page, "Пропустить отдых", "/phase/next");
      await clickAndSync(page, "Готов", "/phase/next");
      await page.getByLabel(/Результат|Секунды|Повторений/).fill("7");
      await clickAndSync(page, "Готово", "/sets:batch");
      await expect(page.getByText("Все подходы плана выполнены")).toBeVisible();
      await expect(page.getByTestId("pause-toggle")).toHaveCount(0);

      await page.getByTestId("extra-set-button").click();
      await expect(page.getByTestId("extra-set-form")).toBeVisible();
      await expectNoHorizontalOverflow(page, "Live: форма ещё подхода");
      await page.getByLabel(/Результат|Секунды|Повторений/).fill("5");
      await clickAndSync(page, "Записать", "/sets:batch");
      await expect(page.getByTestId("extra-count")).toContainText("1");
      expect(batchBodies.flatMap((b) => b.sets).filter((s) => s.is_extra)).toEqual([
        expect.objectContaining({ value: "5", is_extra: true }),
      ]);
      expect(batchBodies.flatMap((b) => b.sets).filter((s) => !s.is_extra)).toHaveLength(2);

      await page.getByRole("button", { name: "Завершить", exact: true }).click();
      await clickAndSync(page, "Сохранить и завершить", "/complete");
      await expect(page.getByText("Тренировка завершена")).toBeVisible();

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}

// --- Live logging panel (#265): панель записи следует за таймером, «Приготовься» в конце отдыха --
// Seeds: session_recovery (reps 3 x 8, отдых 60 с — панель раскрывается сама) и golden_journey
// (reps 2 x 8, отдых 2 с — весь отдых в последних 10 с, панель свёрнута). Реальные часы: отдых
// 60 с не ждём — «Приготовься» проверяем на коротком отдыхе, раскрытие — сразу после подхода.
const PANEL_USERS = {
  320: { long: 980_041, short: 980_061, theme: "light" },
  390: { long: 980_051, short: 980_071, theme: "dark" },
} as const;

async function startFromFreePool(page: Page, title: string) {
  await page.getByTestId("my-workout-card").filter({ hasText: title }).click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await page.getByRole("button", { name: "Свободный пул" }).click();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  const group = page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${title}`) });
  await group.getByRole("button", { name: "Начать", exact: true }).click();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await expect(page.getByText("Живая тренировка")).toBeVisible();
}

for (const width of WIDTHS) {
  const { long, short, theme } = PANEL_USERS[width as 320 | 390];
  test.describe(`Live logging panel @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 760 } });
    test.setTimeout(120_000);

    test("работа — свёрнута; длинный отдых — раскрыта, правка того же подхода без дубля", async ({ page }, testInfo) => {
      page.on("dialog", (dialog) => void dialog.accept());
      const { consoleErrors, apiFailures } = await openAppAs(page, long + testInfo.retry, { theme });
      const batchSets: { set_index: number; value: string; effort: string | null; note: string | null }[] = [];
      page.on("request", (request) => {
        if (request.method() === "POST" && request.url().includes("/sets:batch")) {
          batchSets.push(...request.postDataJSON().sets);
        }
      });
      await startFromFreePool(page, "Тренировка восстановления");

      // Работа: одна строка записи + «Готово» под рукой, оценка/заметка скрыты.
      await clickAndSync(page, "Готов", "/phase/next");
      await expect(page.getByText("Пошёл")).toBeVisible();
      const panel = page.getByTestId("log-panel");
      await expect(panel).toHaveAttribute("data-state", "collapsed");
      await expect(page.getByTestId("set-effort")).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Готово", exact: true })).toBeVisible();
      await expectNoHorizontalOverflow(page, "Live: панель свёрнута");
      await page.getByLabel(/Результат|Секунды|Повторений/).fill("8");
      await clickAndSync(page, "Готово", "/sets:batch");

      // Отдых 60 с (≥ 20): панель раскрылась сама, «Приготовься» ещё рано.
      await expect(page.getByRole("heading", { name: "Отдых", exact: true })).toBeVisible();
      await expect(panel).toHaveAttribute("data-state", "expanded");
      await expect(page.getByTestId("get-ready-cue")).toHaveCount(0);
      await expect(page.getByTestId("set-effort").getByRole("button")).toHaveCount(5);
      await expectNoHorizontalOverflow(page, "Live: панель раскрыта на отдыхе");

      // Правка того же подхода: значение, усилие и заметка уходят тем же set_index.
      await page.getByLabel(/Результат|Секунды|Повторений/).fill("9");
      await page.getByTestId("set-effort").getByRole("button").nth(2).click();
      await page.getByLabel("Заметка", { exact: true }).fill("после отдыха");
      await clickAndSync(page, "Сохранить подход", "/sets:batch");
      expect(batchSets).toHaveLength(2);
      expect(batchSets[1].set_index).toBe(batchSets[0].set_index);
      expect(batchSets[1]).toMatchObject({ value: "9", effort: "3", note: "после отдыха" });

      // Следующий подход: форма заново пустая; правка не плодит второй подход.
      await clickAndSync(page, "Пропустить отдых", "/phase/next");
      await clickAndSync(page, "Готов", "/phase/next");
      await expect(panel).toHaveAttribute("data-state", "collapsed");
      await expect(page.getByLabel(/Результат|Секунды|Повторений/)).toHaveValue("");
      await page.getByLabel(/Результат|Секунды|Повторений/).fill("7");
      await clickAndSync(page, "Готово", "/sets:batch");
      expect(new Set(batchSets.map((entry) => entry.set_index)).size).toBe(2);

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("короткий отдых: «Приготовься» с обратным отсчётом, панель свёрнута, раскрывается вручную", async ({ page }, testInfo) => {
      page.on("dialog", (dialog) => void dialog.accept());
      const { consoleErrors, apiFailures } = await openAppAs(page, short + testInfo.retry, { theme });
      await startFromFreePool(page, EFFORT_TITLE);

      await clickAndSync(page, "Готов", "/phase/next");
      await expect(page.getByTestId("get-ready-cue")).toHaveCount(0); // «Приготовься» — только на отдыхе
      await page.getByLabel(/Результат|Секунды|Повторений/).fill("8");
      await clickAndSync(page, "Готово", "/sets:batch");

      // Отдых 2 с — целиком в последних 10 с: подпись и число секунд видны, панель свёрнута.
      await expect(page.getByRole("heading", { name: "Отдых", exact: true })).toBeVisible();
      await expect(page.getByTestId("get-ready-cue")).toContainText("Приготовься");
      await expect(page.getByTestId("get-ready-countdown")).toHaveText(/^[0-2]$/);
      await expect(page.getByTestId("log-panel")).toHaveAttribute("data-state", "collapsed");
      await expect(page.getByTestId("log-panel-summary")).toContainText("8");
      await expectNoHorizontalOverflow(page, "Live: Приготовься");

      // Вручную: раскрыть, поправить, сохранить — тот же подход.
      await page.getByTestId("log-panel-toggle").click();
      await expect(page.getByTestId("log-panel")).toHaveAttribute("data-state", "expanded");
      await page.getByLabel(/Результат|Секунды|Повторений/).fill("10");
      await clickAndSync(page, "Сохранить подход", "/sets:batch");

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
