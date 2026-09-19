import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py first_workout 900002 — анкета полностью пройдена
// (подписка есть), ни одной тренировки ещё не было. Замер — 5 повторений:
// suggest_starting_equipment(5) даёт (BAND, BODYWEIGHT) — блок A требует
// резину, для которой у свежего пользователя нет ни одного заведённого
// band_item (заводится прямо на форме, "+ Завести новую резину", issue
// #124 PR 3), блок Б идёт на собственном весе.
const TELEGRAM_ID = 900_002;

test("первая тренировка (issue #123, #175): шаг подтверждения снаряда, нет тупиковых кнопок, доходит до записи", async ({
  page,
}) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);

  // Стартовый экран теперь "Главная" (issue #175), не "Тренировка" —
  // переходим на неё явно, прежде чем дойти до шага снаряда/формы ниже.
  await page.getByText("Тренировка", { exact: true }).click();

  // Явный шаг подтверждения стартового снаряда (issue #175, п.2) — раньше
  // снаряд впервые показывался мелкой строкой прямо на форме, теперь
  // отдельный экран перед ней. baseline=5 → suggest_starting_equipment
  // даёт (BAND, BODYWEIGHT): пользователь, которому нужна резина, обязан
  // увидеть это ДО тренировки, не только после того, как форма уже открыта.
  await expect(page.getByText("Стартовый снаряд")).toBeVisible();
  await expect(page.getByText(/Блок A: по результату замера стартуешь на резине/)).toBeVisible();
  await expect(
    page.getByText("Блок Б: справляешься на собственном весе — дополнительный снаряд не нужен."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Понятно, к тренировке" }).click();

  // Регрессия на реальный баг issue #123: до фикса на этом статусе снаряд
  // ни для одного блока ещё не назначен, но экран выбора режима всё равно
  // показывал «Внести пропущенную тренировку»/«Внести свободные
  // подтягивания» — обе вели в тупик (бэкдейт подставлял снаряд-заглушку,
  // резину, которой физически нет, сохранить результат было невозможно).
  // После issue #124 (PR 2) is_first_workout=true пропускает экран выбора
  // режима целиком и сразу открывает форму (см. WorkoutScreen.tsx,
  // useEffect с setShowForm(true)) — эти кнопки не просто скрыты условием,
  // а структурно не рендерятся вообще ни при каком статусе первой
  // тренировки.
  await expect(
    page.getByText(
      "Это твоя первая тренировка — снаряд ниже подобран по замеру, укажи фактическое значение (вес/резину), где это нужно.",
    ),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "🔁 Внести пропущенную тренировку" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "➕ Внести свободные подтягивания" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "🎯 Факультатив" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "⏱ Тренировка в реальном времени" })).toHaveCount(0);

  // Блок A на резине — своего band_item ещё нет, заводим прямо на форме.
  await page.getByLabel("Блок A, резина").selectOption({ label: "+ Завести новую резину" });
  await page.getByLabel("Блок A, название резины").fill("Красная");
  await page.getByRole("button", { name: "Добавить резину" }).click();
  // POST /api/equipment/band-items — ждём реального успеха (форма
  // заведения резины исчезает, см. BandItemSelect::handleCreate), иначе
  // ниже "Записать тренировку" могла бы уйти раньше выбора резины и
  // упасть на серверной валидации "нечего подставить молча" (issue #148).
  await expect(page.getByLabel("Блок A, название резины")).toHaveCount(0);

  for (const n of [1, 2, 3]) {
    await page.getByLabel(`Блок A, подход ${n}`).fill("9");
  }
  await page.getByLabel("Блок A, подход на максимум").fill("10");

  // Блок Б на собственном весе — ничего дополнительно указывать не нужно.
  for (const n of [1, 2, 3, 4]) {
    await page.getByLabel(`Блок B, подход ${n}`).fill("3");
  }
  await page.getByLabel("Блок B, подход на максимум").fill("3");

  await page.getByRole("button", { name: "Записать тренировку" }).click();

  await expect(page.getByText("Тренировка записана")).toBeVisible();

  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});
