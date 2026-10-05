// Journey regression for #297 (FD-02): the FIRST «Добавить в план» of a brand-new user.
//
// RUN (clean DB at head, server on :8102 with BOT_TOKEN=audit-token, NO e2e_seed, NO seeds):
//   su postgres -c "dropdb --if-exists pullup_j_b && createdb -O pullup pullup_j_b"
//   python -m alembic upgrade head      # DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:5432/pullup_j_b
//   python -m uvicorn app.web.main:app --host 127.0.0.1 --port 8102   # BOT_TOKEN=audit-token REDIS_URL=redis://localhost:6379/6
//   cd webapp-frontend/e2e && E2E_BASE_URL=http://127.0.0.1:8102 BOT_TOKEN=audit-token \
//     npx playwright test scenarios/fix-wave1/first-add-to-plan.spec.ts --project=chromium
//   (this sandbox only: pass a config whose launchOptions.executablePath is /opt/pw-browsers/chromium-1194/chrome-linux/chrome)
//
// The user is created through the UI onboarding only (the telegram id is fresh, nothing is seeded):
// Главная → «+» → «Создать тренировку» → имя → «+ Добавить упражнение» → «Создать своё» → «Добавить» →
// «Сохранить» → «Добавить в план» → день → «Добавить» → Планы: строка в текущей неделе (до и после reload) →
// «Начать» → Live → «Завершить» → «1 из 1» (и после reload).
import { expect, test, type Page } from "@playwright/test";

import { openAppAs } from "../../fixtures/setup";

const TELEGRAM_ID = 7_500_000 + (Date.now() % 400_000);
const WORKOUT = "Моя первая тренировка";
const EXERCISE = "Подтягивания тест";

const nav = (page: Page, name: string) => page.getByRole("button", { name, exact: true });

async function onboard(page: Page) {
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

test("первое «Добавить в план» нового пользователя: строка видна, переживает reload, стартует и считается", async ({ page }) => {
  const { apiFailures } = await openAppAs(page, TELEGRAM_ID, { allowedApiStatuses: [404] });
  page.on("dialog", (dialog) => void dialog.accept());
  await onboard(page);

  // Нет плана: «Планы» пусты.
  // Создаём тренировку из ничего.
  await page.getByRole("button", { name: "Быстрые действия" }).click();
  await page.getByRole("button", { name: "Создать тренировку" }).click();
  await page.getByPlaceholder("Например, 3 минуты подтягиваний").fill(WORKOUT);
  await page.getByRole("button", { name: "Создать и добавить упражнения" }).click();
  await page.getByRole("button", { name: "+ Добавить упражнение" }).click();
  await page.getByRole("searchbox").fill(EXERCISE);
  await page.getByRole("button", { name: /Создать своё/ }).click();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByText("3 × 10 повторений")).toBeVisible();

  // ПЕРВОЕ «Добавить в план» — плана у пользователя ещё нет.
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await page.getByRole("button", { name: "Ср", exact: true }).click();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();

  // Сразу после добавления (caller ведёт на «Планы») и после reload — строка в текущей неделе.
  const assertRowInCurrentWeek = async () => {
    await expect(page.getByTestId("plan-week-progress")).toContainText("Текущая неделя");
    await expect(page.getByTestId("plan-week-progress")).toContainText("0 из 1");
    await expect(page.getByText("На эту неделю пока ничего не запланировано.")).toHaveCount(0);
    await expect(page.getByText("СРЕДА")).toBeVisible();
    await expect(page.getByRole("button", { name: new RegExp(`^Начать: ${WORKOUT}`) })).toBeVisible();
  };
  await nav(page, "Планы").click();
  await assertRowInCurrentWeek();
  await page.reload();
  await nav(page, "Планы").click();
  await assertRowInCurrentWeek();

  // Строкой можно управлять: «Действия» открывает лист с «Убрать из плана» (не нажимаем — дальше стартуем).
  await page.getByRole("button", { name: new RegExp(`^Действия: ${WORKOUT}`) }).click();
  await expect(page.getByRole("button", { name: "Убрать из плана" })).toBeVisible();
  await page.keyboard.press("Escape");

  // Старт из «Планов» → Live → завершение.
  await page.getByRole("button", { name: new RegExp(`^Начать: ${WORKOUT}`) }).click();
  await page.getByRole("button", { name: "Начать" }).click();
  await page.getByRole("button", { name: "Готов" }).click();
  await page.getByLabel("Повторений").fill("9");
  await page.getByRole("button", { name: "Готово" }).click();
  await page.getByRole("button", { name: "Пропустить отдых" }).click();
  await page.getByRole("button", { name: "Готов" }).click();
  await page.getByLabel("Повторений").fill("7");
  await page.getByRole("button", { name: "Готово" }).click();
  await page.getByRole("button", { name: "Завершить" }).first().click();
  await page.getByRole("button", { name: /3 Средне/ }).click();
  await page.getByRole("button", { name: "Сохранить и завершить" }).click();
  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  await page.getByRole("button", { name: "Закрыть" }).click();

  await page.reload();
  await nav(page, "Планы").click();
  await expect(page.getByTestId("plan-week-progress")).toContainText("1 из 1");
  expect(apiFailures).toEqual([]);
});
