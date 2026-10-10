/**
 * Fix Wave 1 (#299, #298): custom workout on an EMPTY library, a 0-exercise workout, and the
 * Планы <-> Главная empty-state loop. Journeys run as a brand-new user created through the UI
 * onboarding on a clean DB at head: no e2e_seed, no request.post setup (GET reads only, to make
 * assertions depend on what the API actually returns, since system content ships separately).
 *
 * Run (from webapp-frontend/e2e; server already started on the clean DB with BOT_TOKEN=audit-token,
 * frontend built into webapp-frontend/dist):
 *   BOT_TOKEN=audit-token E2E_BASE_URL=http://127.0.0.1:8103 \
 *   npx playwright test -c scenarios/fix-wave1/playwright.config.ts custom-workout-direct
 * (E2E_CHROMIUM_PATH=/opt/pw-browsers/chromium-1194/chrome-linux/chrome if the default chromium build is missing.)
 */
import { expect, test, type Page } from "@playwright/test";

import { buildInitData, getTestBotToken } from "../../fixtures/initData";
import { playSetsV2 } from "../../fixtures/builderFlow";
import { openAppAs } from "../../fixtures/setup";

const newUserId = () => 7_400_000 + Math.floor(Math.random() * 500_000);

async function onboardViaUi(page: Page, telegramId: number) {
  await openAppAs(page, telegramId);
  await page.getByLabel("Число подтягиваний").fill("8");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByRole("button", { name: "Да" }).click();
  await page.getByRole("button", { name: "Продолжить" }).click();
  await page.getByLabel("Вес, кг").fill("78");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Рост, см").fill("180");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Пол").selectOption({ label: "Мужской" });
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Дата рождения").fill("1992-04-15");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Часовой пояс").selectOption({ label: "Москва (UTC+3)" });
  await page.getByRole("button", { name: "Готово" }).click();
  await expect(page.getByText("Что потренируем сегодня?")).toBeVisible();
}

/** Read-only GET as the user (assertions follow what the API returns). */
async function apiGet<T>(page: Page, telegramId: number, path: string): Promise<T> {
  const initData = buildInitData({ id: telegramId, firstName: "E2E" }, getTestBotToken());
  const response = await page.request.get(path, { headers: { "X-Telegram-Init-Data": initData } });
  expect(response.ok(), `GET ${path}`).toBeTruthy();
  return (await response.json()) as T;
}

async function startCreateWorkout(page: Page, title: string) {
  await page.getByRole("button", { name: "Баннер: собрать свой комплекс" }).click();
  await page.getByPlaceholder("Например, 3 минуты подтягиваний").fill(title);
  await page.getByRole("button", { name: "Создать и добавить упражнения" }).click();
  await expect(page.getByText("Пока пусто. Добавьте первое упражнение")).toBeVisible();
}

/**
 * In the picker: create an exercise through whatever the screen offers.
 * Empty library -> visible "Создать упражнение" form without typing; non-empty -> no-match row.
 */
async function createExerciseInPicker(page: Page, name: string, libraryCount: number) {
  if (libraryCount === 0) {
    await expect(page.getByTestId("picker-empty-library")).toBeVisible();
    await expect(page.getByTestId("picker-empty-library-text")).toContainText("Создайте первое");
    // Visible create action BEFORE any typing (it is disabled until a name is entered, but it is there).
    await expect(page.getByRole("button", { name: /^Создать упражнение/ })).toBeVisible();
    await page.getByLabel("Название упражнения").fill(name);
    await page.getByRole("button", { name: `Создать упражнение «${name}»` }).click();
  } else {
    // System/own exercises are listed (conditional on what the API returned).
    await expect(page.locator(".ux-pick:not(.ux-pick-create)").first()).toBeVisible();
    await page.getByRole("searchbox", { name: "Поиск упражнения" }).fill(name);
    await expect(page.getByText("Ничего не найдено")).toBeVisible();
    await page.getByRole("button", { name: `Создать своё упражнение: «${name}»` }).click();
  }
  await expect(page.getByText("ТИП РАБОТЫ")).toBeVisible();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  await expect(page.getByTestId("workout-item")).toHaveCount(1);
}

test("новый пользователь: своя тренировка с нуля -> упражнение -> протокол -> сохранить -> перезагрузка -> начать -> журнал", async ({ page }) => {
  const uid = newUserId();
  await onboardViaUi(page, uid);
  const library = await apiGet<{ exercises: Array<{ id: number; name: string }> }>(page, uid, "/api/v2/exercises");

  await startCreateWorkout(page, "Прямая тренировка");
  await page.getByRole("button", { name: "+ Добавить упражнение" }).click();
  await expect(page.getByRole("heading", { name: "Добавить упражнение" })).toBeVisible();
  if (library.exercises.length > 0) {
    // If system exercises exist they are listed in the picker.
    await expect(page.locator(".ux-pick", { hasText: library.exercises[0].name }).first()).toBeVisible();
  }
  await createExerciseInPicker(page, "Мои подтягивания", library.exercises.length);
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByTestId("workout-detail")).toBeVisible();
  await expect(page.getByTestId("workout-detail-start")).toBeEnabled();
  await expect(page.getByTestId("workout-detail-items")).toContainText("Мои подтягивания");

  // Перезагрузка: тренировка на месте, стартует напрямую (без плана).
  await page.reload();
  await expect(page.getByText("Что потренируем сегодня?")).toBeVisible();
  await page.getByTestId("my-workout-card").filter({ hasText: "Прямая тренировка" }).click();
  await expect(page.getByTestId("workout-detail-items")).toContainText("Мои подтягивания");
  await page.getByTestId("workout-detail-start").click();

  await expect(page.getByText("ГОТОВЫ К СТАРТУ")).toBeVisible();
  await page.getByRole("button", { name: "Начать" }).click();
  // issue #306 (Live Engine v2): без «Готов»/«Пропустить отдых»; после последнего подхода — досрочное завершение с оценкой.
  await playSetsV2(page, ["8"]);
  await expect(page.getByText("Подход 1: 8 повт.")).toBeVisible();
  await playSetsV2(page, ["6"]);
  await page.getByTestId("engine-finish").click(); // досрочно: план длиннее двух подходов
  await page.getByRole("button", { name: /3 Средне/ }).click();
  await page.getByTestId("engine-finish-confirm").click();
  await expect(page.getByText("Подход 2: 6 повт.")).toBeVisible();

  await page.reload();
  await page.getByRole("button", { name: "Журнал", exact: true }).click();
  await expect(page.getByText("Свободная").first()).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Журнал", exact: true }).click();
  await expect(page.getByText("Свободная").first()).toBeVisible();
});

test("тренировка без упражнений: причина рядом с «Начать» и один тап до выбора упражнения", async ({ page }) => {
  const uid = newUserId();
  await onboardViaUi(page, uid);
  const library = await apiGet<{ exercises: Array<{ id: number; name: string }> }>(page, uid, "/api/v2/exercises");

  await startCreateWorkout(page, "Пустая тренировка");
  // «Добавить в план» в редакторе пустой тренировки заблокирован (иначе — серверная ошибка 422).
  await expect(page.getByRole("button", { name: "Добавить в план" })).toBeDisabled();
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByTestId("workout-detail")).toBeVisible();

  // Причина видна, действия заблокированы, а не «молчат».
  await expect(page.getByTestId("workout-detail-start")).toBeDisabled();
  await expect(page.getByTestId("workout-detail-log")).toBeDisabled();
  await expect(page.getByTestId("workout-detail-add-to-plan")).toBeDisabled();
  await expect(page.getByTestId("workout-detail-empty-reason")).toContainText("нет упражнений");
  await expect(page.getByTestId("workout-detail-start")).toHaveAttribute("aria-describedby", "workout-detail-empty-reason");

  // Один тап «Добавить упражнение» -> сразу выбор упражнения этой тренировки.
  await page.getByTestId("workout-detail-add-exercise").click();
  await expect(page.getByRole("heading", { name: "Добавить упражнение" })).toBeVisible();
  await createExerciseInPicker(page, "Отжимания тест", library.exercises.length);
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByTestId("workout-detail-start")).toBeEnabled();
  await expect(page.getByTestId("workout-detail-empty")).toHaveCount(0);
  await page.reload();
  await page.getByTestId("my-workout-card").filter({ hasText: "Пустая тренировка" }).click();
  await expect(page.getByTestId("workout-detail-items")).toContainText("Отжимания тест");
});

test("E1: «Планы» без плана не зацикливается с «Главной» — каждый CTA ведёт к действию", async ({ page }) => {
  const uid = newUserId();
  await onboardViaUi(page, uid);
  const { programs } = await apiGet<{ programs: Array<{ id: number }> }>(page, uid, "/api/v2/programs");
  const hasCourses = programs.length > 0;

  await page.getByRole("button", { name: "Планы", exact: true }).click();
  await expect(page.getByTestId("plans-now-empty")).toBeVisible();

  if (hasCourses) {
    // Каталог есть: CTA ведёт на Главную, где сразу видны карточки курсов (полезное открытие), цикла нет.
    await page.getByRole("button", { name: "Выбрать курс на Главной" }).click();
    await expect(page.getByTestId("program-category").first()).toBeVisible();
    await page.getByRole("button", { name: "Баннер: план дня пуст" }).click();
    await expect(page.getByTestId("program-category").first()).toBeInViewport();
  } else {
    // Каталога нет: честное «пока нет» + прямой путь «Создать тренировку» (не «появится позже» навсегда).
    await expect(page.getByTestId("plans-now-empty")).toContainText("каталог пуст");
    await expect(page.getByRole("button", { name: "Выбрать курс на Главной" })).toHaveCount(0);
    await page.getByRole("button", { name: "Создать тренировку" }).click();
    await expect(page.getByPlaceholder("Например, 3 минуты подтягиваний")).toBeVisible();

    // Главная: каталог тоже честно пуст, а баннер «план дня» ведёт не в пустые «Планы», а к созданию.
    await page.reload();
    await expect(page.getByTestId("catalog-empty")).toBeVisible();
    await page.getByRole("button", { name: "Баннер: план дня пуст" }).click();
    await expect(page.getByPlaceholder("Например, 3 минуты подтягиваний")).toBeVisible();
  }
});
