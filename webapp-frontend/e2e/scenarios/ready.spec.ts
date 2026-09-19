import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py ready 900003 — одна прошлая тренировка 5 дней назад,
// снаряд обоих блоков уже BAND (см. scripts/e2e_seed.py::seed_ready).
const TELEGRAM_ID = 900_003;

test("обычный день тренировки: пять вкладок навигации, потом полный путь ввода результата до записи", async ({
  page,
}) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);

  // "Главная" (волна 5b, issue #183, crimpd-reference skill) — новый
  // стартовый экран Mini App вместо сразу открытой формы тренировки
  // (product-reference skill, референс — Crimpd): компактный виджет "на
  // этой неделе" + честная заглушка под каталог курсов (волна 6, ещё не
  // сделан — не имитация рабочего списка).
  await expect(page.getByText("Готов к тренировке.")).toBeVisible();
  await expect(page.getByText("Скоро здесь появится каталог курсов")).toBeVisible();

  // Ровно пять пунктов нижнего меню, "Тренировка" среди них нет — открыть
  // форму можно только кнопкой (см. ниже), не пунктом меню.
  for (const label of ["Главная", "Планы", "Журнал", "Аналитика", "Профиль"]) {
    await expect(page.getByRole("button", { name: label })).toBeVisible();
  }
  await expect(page.getByRole("button", { name: "Тренировка", exact: true })).toHaveCount(0);

  // "Планы" — бывший Dashboard (issue #175), содержимое не переписывалось
  // (issue #183: только переезд) — тот же текст готовности и те же счётчики.
  await page.getByRole("button", { name: "Планы" }).click();
  await expect(page.getByText("Готов к тренировке.")).toBeVisible();
  await expect(page.getByText("Тренировок всего")).toBeVisible();

  // "Журнал" (бывшая "История", не переписывалась) — у этого сценария уже
  // есть одна тренировка, список не пустой.
  await page.getByRole("button", { name: "Журнал" }).click();
  await expect(page.locator(".history-card")).toHaveCount(1);

  // "Аналитика" (бывший "Прогресс", не переписывалась) — с одной
  // тренировкой графику не из чего строиться, это ожидаемое пустое
  // состояние, не баг.
  await page.getByRole("button", { name: "Аналитика" }).click();
  await expect(
    page.getByText("Пока недостаточно тренировок для графика — нужно хотя бы две."),
  ).toBeVisible();

  // "Профиль" (не переписывался).
  await page.getByRole("button", { name: "Профиль" }).click();
  await expect(page.getByText("Разряд ГТО (подтягивание)")).toBeVisible();

  // "Тренировка" открывается кнопкой с "Планов" (тот же путь, что раньше
  // был кнопкой на Dashboard) — назад ведёт клик по любой вкладке Tabbar,
  // она остаётся видимой поверх формы (telegram-miniapp skill: "экран, с
  // которого нельзя вернуться — ошибка"; SDK BackButton недоступен вне
  // настоящего Telegram-клиента — mockTelegramWebApp не поднимает мост
  // postEvent, — так что здесь проверяем именно этот запасной путь).
  await page.getByRole("button", { name: "Планы" }).click();
  await page.getByRole("button", { name: "Начать тренировку" }).click();
  await expect(page.getByText("Текущий план")).toBeVisible();
  await page.getByRole("button", { name: "Планы" }).click();
  await expect(page.getByText("Готов к тренировке.")).toBeVisible();

  // Теперь по-настоящему проходим форму до записи.
  await page.getByRole("button", { name: "Начать тренировку" }).click();

  await expect(page.getByText("Текущий план")).toBeVisible();
  await page.getByRole("button", { name: "📝 Внести результат тренировки" }).click();

  // work_sets_a=3/work_sets_b=4 для этого сидирования (подтверждено
  // tests/test_web/test_workout.py::test_plan_ready_shows_target_and_equipment)
  // — те же значения, что и в прошлой тренировке, чтобы гарантированно не
  // задеть detect_anomalies (резкий скачок относительно среднего) и дойти
  // до записи без промежуточного экрана подтверждения аномалии.
  for (const n of [1, 2, 3]) {
    await page.getByLabel(`Блок A, подход ${n}`).fill("10");
  }
  await page.getByLabel("Блок A, подход на максимум").fill("11");

  for (const n of [1, 2, 3, 4]) {
    await page.getByLabel(`Блок B, подход ${n}`).fill("3");
  }
  await page.getByLabel("Блок B, подход на максимум").fill("3");

  await page.getByRole("button", { name: "Записать тренировку" }).click();

  await expect(page.getByText("Тренировка записана")).toBeVisible();

  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});
