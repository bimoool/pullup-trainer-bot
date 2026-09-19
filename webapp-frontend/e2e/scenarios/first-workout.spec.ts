import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py first_workout 900002 — анкета полностью пройдена
// (подписка есть), ни одной тренировки ещё не было. Замер — 6 повторений:
// suggest_starting_equipment(6) даёт (BAND, BODYWEIGHT) — блок на объём
// стартует на резине (снаряд нужно подготовить заранее), блок на силу — на
// собственном весе (снаряд не нужен вовсе). Сознательный выбор именно этой
// комбинации (issue #175) — сценарий должен реально проверять новый экран
// подтверждения стартового снаряда (EquipmentPlanScreen.tsx) на случае,
// где что-то нужно подготовить/завести, а не только на случае "не нужно".
const TELEGRAM_ID = 900_002;

test("первая тренировка (issue #175): Dashboard → подтверждение снаряда → форма → запись", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);

  // Волна 5b (issue #183) — стартовый экран теперь "Главная" (каталог),
  // а прежний Dashboard целиком переехал на вкладку "Планы" (crimpd-reference
  // skill: стартовый экран — каталог, не план).
  await page.getByRole("button", { name: "Планы" }).click();

  // Dashboard (issue #175) — честно предупреждает, что это первая
  // тренировка, ДО того как вести к форме.
  await expect(
    page.getByText("Это будет твоя первая тренировка — сначала подберём снаряд по замеру."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Начать тренировку" }).click();

  // Экран подтверждения стартового снаряда (issue #175) — показан ДО формы,
  // не мелкой строкой на ней (регрессия на исходную жалобу issue: снаряд
  // впервые упоминался мелким текстом прямо на форме ввода результата).
  // Блок на объём — резина, её нужно подготовить/завести заранее.
  await expect(page.getByText("Блок на объём — резина.")).toBeVisible();
  await expect(
    page.getByText("Понадобится резина — выбери из уже заведённых или заведи новую на следующем экране."),
  ).toBeVisible();
  // Блок на силу — собственный вес, снаряд явно назван ненужным, не молчание.
  await expect(page.getByText("Блок на силу — собственный вес.")).toBeVisible();
  await expect(page.getByText("Доп. снаряд не нужен — тренируешься на собственном весе.")).toBeVisible();

  // Форма ввода результата ещё не должна быть на экране, пока снаряд не
  // подтверждён явным нажатием.
  await expect(page.getByLabel("Блок A, подход 1")).toHaveCount(0);

  await page.getByRole("button", { name: "Начать тренировку" }).click();

  // Регрессия на issue #123: до фикса на статусе первой тренировки экран
  // выбора режима всё равно показывал тупиковые кнопки — здесь их не должно
  // быть вообще, форма открыта сразу после подтверждения снаряда.
  await expect(page.getByRole("button", { name: "🔁 Внести пропущенную тренировку" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "➕ Внести свободные подтягивания" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "🎯 Факультатив" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "⏱ Тренировка в реальном времени" })).toHaveCount(0);

  // Блок A — резина, заводим новую прямо на форме (issue #124, PR 3).
  await page.getByLabel("Блок A, резина").selectOption("__new__");
  await page.getByLabel("Блок A, название резины").fill("Красная");
  await page.getByLabel("Блок A, сопротивление резины").fill("15");
  await page.getByRole("button", { name: "Добавить резину" }).click();

  for (const n of [1, 2, 3]) {
    await page.getByLabel(`Блок A, подход ${n}`).fill("9");
  }
  await page.getByLabel("Блок A, подход на максимум").fill("10");

  // Блок Б — собственный вес, ни резины, ни веса указывать не нужно.
  await expect(page.getByLabel("Блок B, резина")).toHaveCount(0);
  await expect(page.getByLabel("Блок B, фактический вес")).toHaveCount(0);
  for (const n of [1, 2, 3, 4]) {
    await page.getByLabel(`Блок B, подход ${n}`).fill("3");
  }
  await page.getByLabel("Блок B, подход на максимум").fill("3");

  await page.getByRole("button", { name: "Записать тренировку" }).click();

  await expect(page.getByText("Тренировка записана")).toBeVisible();

  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});
