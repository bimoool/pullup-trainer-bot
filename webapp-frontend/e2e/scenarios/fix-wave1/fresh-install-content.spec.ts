import { expect, type Page, test } from "@playwright/test";

import { finishV2, noWakeLock, playSetsV2 } from "../../fixtures/builderFlow";
import { openJournalEntry } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";

/**
 * Fix Wave 1, #296 (FD-01/FD-06/FD-07): системный контент приезжает вместе с `alembic upgrade head`.
 *
 * ЗАПУСК против БД «только миграции» (никаких seed-скриптов, никакого scripts/e2e_seed.py):
 *
 *   createdb pullup_fresh && DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:5432/pullup_fresh \
 *     BOT_TOKEN=audit-token python -m alembic upgrade head
 *   DATABASE_URL=... BOT_TOKEN=audit-token REDIS_URL=redis://localhost:6379/5 \
 *     python -m uvicorn app.web.main:app --port 8101 &
 *   cd webapp-frontend && npm run build   # статику отдаёт тот же uvicorn
 *   cd e2e && E2E_BASE_URL=http://127.0.0.1:8101 BOT_TOKEN=audit-token \
 *     npx playwright test scenarios/fix-wave1/fresh-install-content.spec.ts --project=chromium
 *
 * (Если установленный в системе chromium не совпадает с билдом, который ждёт Playwright, запускайте с
 * конфигом, где `launchOptions.executablePath` указывает на имеющийся chrome; тесты от этого не зависят.)
 *
 * Каждый тест — НОВЫЙ Telegram-пользователь, который проходит онбординг через UI (замер → профиль),
 * и дальше действует только кликами по тексту/ролям: ни `request.post`, ни seed под пользователя.
 * Тесты независимы друг от друга и не требуют ничего, кроме поставляемого каталога
 * (программа «Подтягивания», библиотека упражнений D1, готовые тренировки D2).
 */

// Уникальный id на каждый тест/прогон, чтобы повторный запуск на той же БД тоже стартовал с нуля.
let nextId = 7_400_000 + Math.floor(Math.random() * 500_000) * 10;
const freshTelegramId = () => (nextId += 1);

/** Онбординг глазами пользователя: замер → «Да» → профиль → «Готово». */
async function onboardThroughUi(page: Page): Promise<void> {
  await page.getByLabel("Сколько подтягиваний вышло?").fill("8");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByRole("button", { name: "Да", exact: true }).click();
  await page.getByRole("button", { name: "Продолжить" }).click();
  await page.getByLabel("Пол").selectOption({ label: "Мужской" });
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Дата рождения").fill("1992-04-15");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Часовой пояс").selectOption({ label: "Москва (UTC+3)" });
  await page.getByRole("button", { name: "Готово" }).click();
  await expect(page.getByText("Что потренируем сегодня?")).toBeVisible();
}

async function openFreshHome(page: Page, liveEngine: "v1" | "v2" = "v1") {
  const watchers = await openAppAs(page, freshTelegramId(), { liveEngine });
  await onboardThroughUi(page);
  return watchers;
}

const D1_LIBRARY = [
  "Подтягивания",
  "Подтягивания с резиной",
  "Подтягивания с отягощением",
  "Австралийские подтягивания",
  "Лопаточные подтягивания",
  "Вис на турнике",
  "Планка",
  "Отжимания",
];

test("новый пользователь: Главная → «Подтягивания» → в план → курс стартуемый в Планах, после перезагрузки тоже", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openFreshHome(page);

  // Сначала дождаться самого каталога (иначе «пустого» текста ещё нет просто потому, что не загрузилось).
  await expect(page.getByTestId("program-row").first()).toBeVisible();
  await expect(page.getByText("Каталог курсов появится здесь позже.")).toHaveCount(0);
  await page.getByRole("button", { name: /^Подтягивания/ }).first().click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await expect(page.getByRole("button", { name: "В плане", exact: true })).toBeVisible();

  // На деталях курса нижней навигации нет — «назад», затем вкладка «Планы».
  await page.getByRole("button", { name: /Назад/ }).first().click();
  await page.getByRole("button", { name: "Планы", exact: true }).click();
  const startRow = page.getByRole("button", { name: /^Начать: Подтягивания/ }).first();
  await expect(startRow).toBeVisible();

  await page.reload();
  await page.getByRole("button", { name: "Планы", exact: true }).click();
  await expect(page.getByRole("button", { name: /^Начать: Подтягивания/ }).first()).toBeVisible();

  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});

test("новый пользователь: «Создать тренировку» → «+ Добавить упражнение» — системные упражнения видны без ввода, «Факультатив» нет", async ({ page }) => {
  const { apiFailures } = await openFreshHome(page);

  await page.getByRole("button", { name: "Создать тренировку" }).click();
  await page.getByPlaceholder("Например, 3 минуты подтягиваний").fill("Моя проверка");
  await page.getByRole("button", { name: "Создать и добавить упражнения" }).click();
  await page.getByRole("button", { name: "+ Добавить упражнение" }).click();

  // Ничего не набираем: библиотека видна сразу.
  for (const name of D1_LIBRARY) {
    await expect(page.getByText(name, { exact: true }).first(), `в пикере нет «${name}»`).toBeVisible();
  }
  await expect(page.getByText(/Факультатив/)).toHaveCount(0);
  await expect(page.getByText("Подтягивания — объём")).toHaveCount(0);
  await expect(page.getByText("Подтягивания — сила")).toHaveCount(0);

  // Поиск тоже не подмешивает внутренние упражнения.
  await page.getByRole("searchbox").fill("подтягивания");
  await expect(page.getByText("Австралийские подтягивания", { exact: true })).toBeVisible();
  await expect(page.getByText(/Факультатив/)).toHaveCount(0);

  expect(apiFailures).toEqual([]);
});

test("новый пользователь: готовая тренировка находится в поиске и на Главной, детали → «Начать» ведут к старту", async ({ page }) => {
  const { apiFailures } = await openFreshHome(page);

  // 1) Через поиск: «W-лесенка» → детали (системную тренировку нельзя «Изменить») → «Начать» доступна.
  await page.getByTestId("home-search-pill").click();
  await page.getByRole("searchbox").fill("лесенка");
  await page.getByText("W-лесенка", { exact: true }).first().click();
  await expect(page.getByRole("button", { name: "Начать", exact: true })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Изменить" })).toHaveCount(0);

  // 2) С Главной: секция готовых тренировок, все четыре.
  await page.reload();
  const section = page.getByTestId("system-workouts");
  for (const title of ["Максимум подтягиваний", "W-лесенка", "3 минуты подтягиваний", "Объём ×5"]) {
    await expect(section.getByText(title, { exact: true }), `на Главной нет «${title}»`).toBeVisible();
  }
  await section.getByRole("button", { name: /Максимум подтягиваний/ }).click();
  await expect(page.getByTestId("workout-detail-items")).toContainText("Подтягивания");
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  // предэкран старта → живая тренировка
  await expect(page.getByText("Готовы к старту", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await expect(page.getByText("Живая тренировка", { exact: false }).first()).toBeVisible();

  expect(apiFailures).toEqual([]);
});

test("J3: W-лесенка проводит 17 подходов по рецепту и сохраняет их в Журнале", async ({ page }) => {
  test.setTimeout(90_000);
  const { consoleErrors, apiFailures } = await openFreshHome(page, "v2");
  const title = "W-лесенка";
  const targets = [5, 4, 3, 2, 1, 2, 3, 4, 5, 4, 3, 2, 1, 2, 3, 4, 5];
  const recipe = `${targets.join("-")} · отдых 0:10`;
  await page.getByTestId("system-workouts").getByRole("button", { name: title }).click();
  await expect(page.getByTestId("workout-detail-items")).toContainText(recipe);
  await page.getByTestId("workout-detail-start").click();
  await expect(page.getByText("Готовы к старту", { exact: true })).toBeVisible();
  await expect(page.getByText(recipe, { exact: false })).toBeVisible();

  const started = page.waitForResponse((response) =>
    response.url().endsWith("/api/v2/sessions/live") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  const response = await started;
  expect(response.ok()).toBe(true);
  const session = await response.json();
  expect(session.engine_version).toBe(2);
  expect(session.engine.plan.blocks).toHaveLength(1);
  const sets: { target: number; rest_after_seconds: number | null }[] = session.engine.plan.blocks[0].sets;
  expect(sets.map((set) => [set.target, set.rest_after_seconds])).toEqual(
    targets.map((target, index) => [target, index < targets.length - 1 ? 10 : null]),
  );

  const phase = page.getByTestId("engine-phase");
  for (const [index, target] of targets.entries()) {
    await expect(phase).toHaveText(/Приготовься|Отдых|Пошёл/);
    if ((await phase.textContent())?.trim() !== "Пошёл") {
      await page.getByTestId("engine-skip").click();
    }
    await expect(phase).toHaveText("Пошёл");
    await expect(page.getByTestId("engine-target")).toHaveText(`Подход ${index + 1}/17 · Цель: ${target} повт.`);
    await playSetsV2(page, [String(target)]);
  }
  await finishV2(page);
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  await page.reload();
  await page.getByRole("button", { name: "Журнал", exact: true }).click();
  const entry = page.getByTestId("journal-card").filter({ hasText: title });
  await expect(entry).toHaveCount(1);
  await openJournalEntry(page, entry);
  const sequence = targets.join(" · ");
  await expect(page.getByText(`План: ${sequence}`, { exact: true })).toBeVisible();
  await expect(page.getByText(`Факт: ${sequence}`, { exact: true })).toBeVisible();
  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});
