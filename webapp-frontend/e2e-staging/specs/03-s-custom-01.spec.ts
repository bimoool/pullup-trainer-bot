import { clickAndSync, confirmPreScreen, expect, nav, playSets, test } from "../fixtures/app";

/**
 * S-CUSTOM-01 — own workout: create -> add exercise (system exercises visible with no typing) -> nonsense search ->
 * «Создать своё упражнение» -> create -> add -> save -> reload -> start directly (no plan) -> complete ->
 * add to plan (current week) -> visible after reload -> start from Plans.
 * Runs as qa_fresh_active; names carry a timestamp so reruns never collide.
 */
const stamp = Date.now().toString().slice(-6);
const WORKOUT = `QA Тренировка ${stamp}`;
const EXERCISE = `QA Упражнение ${stamp}`;
const SYSTEM_EXERCISES = ["Подтягивания", "Подтягивания с резиной", "Отжимания", "Планка"];

test("S-CUSTOM-01: own workout from scratch to plan, persisted across reloads", async ({ qa }, testInfo) => {
  const s = await qa("qa_fresh_active");
  const { page } = s;
  await nav(page, "Главная").click();

  await page.getByRole("button", { name: "Баннер: собрать свой комплекс" }).click();
  await page.getByPlaceholder("Например, 3 минуты подтягиваний").fill(WORKOUT);
  await page.getByRole("button", { name: "Создать и добавить упражнения" }).click();
  await expect(page.getByText("Пока пусто. Добавьте первое упражнение")).toBeVisible();
  await page.getByRole("button", { name: "+ Добавить упражнение" }).click();
  await expect(page.getByRole("heading", { name: "Добавить упражнение" })).toBeVisible();

  // System library visible immediately, nothing typed.
  for (const name of SYSTEM_EXERCISES) {
    await expect(page.getByText(name, { exact: true }).first(), `picker misses system exercise «${name}»`).toBeVisible();
  }
  await page.screenshot({ path: testInfo.outputPath("s-custom-01-picker.png") });

  // Nonsense search -> create path.
  await page.getByRole("searchbox", { name: "Поиск упражнения" }).fill(EXERCISE);
  await expect(page.getByText("Ничего не найдено")).toBeVisible();
  await page.getByRole("button", { name: `Создать своё упражнение: «${EXERCISE}»` }).click();
  await expect(page.getByText("ТИП РАБОТЫ")).toBeVisible();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  await expect(page.getByTestId("workout-item")).toHaveCount(1);
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByTestId("workout-detail")).toBeVisible();
  await expect(page.getByTestId("workout-detail-items")).toContainText(EXERCISE);
  await expect(page.getByTestId("workout-detail-start")).toBeEnabled();

  // Persistence, then DIRECT start (no plan row exists).
  await page.reload();
  await page.getByTestId("my-workout-card").filter({ hasText: WORKOUT }).click();
  await expect(page.getByTestId("workout-detail-items")).toContainText(EXERCISE);
  await page.getByTestId("workout-detail-start").click();
  await confirmPreScreen(page);
  await clickAndSync(page, "Готов", "/phase/next");
  await page.getByLabel(/Результат|Секунды|Повторений/).fill("8");
  await clickAndSync(page, "Готово", "/sets:batch");
  await page.getByRole("button", { name: "Завершить", exact: true }).first().click();
  await clickAndSync(page, "Сохранить и завершить", "/complete");
  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  await page.getByRole("button", { name: "Закрыть" }).click();

  // Add to the current plan week.
  await page.reload();
  await page.getByTestId("my-workout-card").filter({ hasText: WORKOUT }).click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await page.getByRole("button", { name: "Свободный пул" }).click();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  const group = () => page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${WORKOUT}`) });
  await expect(group()).toBeVisible();

  // Visible after reload, startable from Plans.
  await page.reload();
  await nav(page, "Планы").click();
  await expect(group()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("s-custom-01-plans.png") });
  await group().getByRole("button", { name: /^Начать: / }).click();
  await confirmPreScreen(page);
  await playSets(page, ["8"]);
  await page.getByRole("button", { name: "Завершить", exact: true }).first().click();
  await clickAndSync(page, "Сохранить и завершить", "/complete");
  await expect(page.getByText("Тренировка завершена")).toBeVisible();

  s.assertClean();
});
