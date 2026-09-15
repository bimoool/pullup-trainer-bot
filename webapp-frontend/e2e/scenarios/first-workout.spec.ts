import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py first_workout 900002 — анкета полностью пройдена
// (подписка есть), ни одной тренировки ещё не было. Замер — 12
// повторений: suggest_starting_equipment(12) даёт (BODYWEIGHT, WEIGHT), не
// BAND — на 10 блок A стартовал бы с резины, для которой у свежего
// пользователя нет ни одного заведённого band_item (issue #124, PR 3 ещё
// не сделан), форма не смогла бы дойти до отправки (см. scripts/e2e_seed.py).
const TELEGRAM_ID = 900_002;

test("первая тренировка (issue #123): нет тупиковых кнопок, форма сразу открыта и доходит до записи", async ({
  page,
}) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);

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

  // Полный путь до записи — блок A на собственном весе (без резины/веса,
  // ничего дополнительно указывать не нужно), блок Б на отягощении (вес
  // указывается прямо тут, обязательно для первой тренировки).
  for (const n of [1, 2, 3]) {
    await page.getByLabel(`Блок A, подход ${n}`).fill("9");
  }
  await page.getByLabel("Блок A, подход на максимум").fill("10");

  for (const n of [1, 2, 3, 4]) {
    await page.getByLabel(`Блок B, подход ${n}`).fill("3");
  }
  await page.getByLabel("Блок B, подход на максимум").fill("3");
  await page.getByLabel("Блок B, фактический вес").fill("5");

  await page.getByRole("button", { name: "Записать тренировку" }).click();

  await expect(page.getByText("Тренировка записана")).toBeVisible();

  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});
