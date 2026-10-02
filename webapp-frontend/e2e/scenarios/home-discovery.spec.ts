import { expect, test, type Page } from "@playwright/test";

import { noWakeLock } from "../fixtures/builderFlow";
import { openAppAs } from "../fixtures/setup";
import { pressTelegramBackButton } from "../fixtures/telegramMock";

// scripts/e2e_seed.py home_workouts — 920001 (только чтение): две свои Workout
// (длинное русское название с тремя упражнениями и пустая) + чужая Workout,
// которой на Главной быть не должно. 920002 — тот же набор для сценария
// создания (мутирует данные, поэтому свой пользователь: retries не ломают счёт).
const READ_ID = 920_001;
const CREATE_ID = 920_002;

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

for (const width of [320, 390]) {
  test(`Главная @${width}px: Программы, Мои тренировки, чужие не видны, без переполнения`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    const { consoleErrors, apiFailures } = await openAppAs(page, READ_ID);

    await expect(page.locator(".plan-title")).toHaveText("Главная");
    // Программы остались (каталог из миграций).
    await expect(page.locator(".program-card-button").first()).toBeVisible();

    // Мои тренировки: ровно две свои, чужая не видна.
    const cards = page.getByTestId("my-workout-card");
    await expect(cards).toHaveCount(2);
    const long = cards.filter({ hasText: "Очень длинная утренняя тренировка" });
    await expect(long).toContainText("3 упражнения");
    await expect(long).toContainText("3 × 8");
    await expect(long).toContainText("Подтягивания · Отжимания +1");
    await expect(cards.filter({ hasText: "Пустая заготовка" })).toContainText("Пока без упражнений");
    await expect(page.getByText("Чужая тренировка")).toHaveCount(0);

    // Ничего технического.
    await expect(page.getByTestId("my-workouts")).not.toContainText(/reps_sets|source_type|owner|undefined|null|NaN|\{|\}/);

    // Нижняя навигация не перекрывает последнюю карточку.
    await cards.last().scrollIntoViewIfNeeded();
    const nav = page.locator(".bottom-tabbar");
    await expect(nav).toBeVisible();
    const cardBox = (await cards.last().boundingBox())!;
    const navBox = (await nav.boundingBox())!;
    expect(cardBox.y + cardBox.height).toBeLessThanOrEqual(navBox.y + 1);
    await expectNoHorizontalOverflow(page);

    // G4: подписи пяти вкладок читаются целиком (не "Г…") и не выходят за свою кнопку.
    const clipped = await nav.locator("button").evaluateAll((buttons) =>
      buttons.filter((button) => {
        const label = button.querySelector(":scope > span") as HTMLElement | null;
        return !label || label.scrollWidth > button.clientWidth || label.getBoundingClientRect().width > button.clientWidth;
      }).length,
    );
    expect(clipped).toBe(0);

    expect(noWakeLock(consoleErrors)).toEqual([]);
    expect(apiFailures).toEqual([]);
  });
}

test("Главная: открыть Мою тренировку, создать новую, навигация цела", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, CREATE_ID, { backButton: true });

  // Открыть существующую → деталь (#255) → «Изменить» → редактор → «Сохранить» → деталь → назад на Главную.
  await page.getByTestId("my-workout-card").filter({ hasText: "Очень длинная" }).click();
  await expect(page.getByTestId("workout-detail")).toBeVisible();
  await page.getByRole("button", { name: "Изменить", exact: true }).click();
  await expect(page.getByText("Редактировать тренировку")).toBeVisible();
  await expect(page.getByText("Подтягивания", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByTestId("workout-detail")).toBeVisible();
  await pressTelegramBackButton(page);
  await expect(page.getByTestId("my-workouts")).toBeVisible();

  // Создать: вход с Главной → форма → сохранение → редактор → «Сохранить» → Главная с новой карточкой.
  const title = `Новая из E2E ${Date.now()}`;
  await page.getByRole("button", { name: "Создать", exact: true }).click();
  await expect(page.getByText("Новая тренировка", { exact: true })).toBeVisible();
  await page.getByRole("textbox").fill(title);
  await page.getByRole("button", { name: "Создать и добавить упражнения" }).click();
  await expect(page.getByText("Редактировать тренировку")).toBeVisible();
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByTestId("workout-detail-title")).toHaveText(title);
  await pressTelegramBackButton(page);
  await expect(page.getByTestId("my-workout-card").filter({ hasText: title })).toBeVisible();
  await expect(page.getByTestId("my-workout-card")).toHaveCount(3);

  // Навигация по пяти вкладкам цела.
  for (const name of ["Планы", "Журнал", "Аналитика", "Профиль", "Главная"]) {
    await page.getByRole("button", { name }).click();
  }
  await expect(page.getByTestId("my-workouts")).toBeVisible();

  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});
