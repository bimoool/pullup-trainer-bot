import { expect, test, type Page } from "@playwright/test";

import { noWakeLock } from "../fixtures/builderFlow";
import { openAppAs } from "../fixtures/setup";

// UX-1: Builder понятен без инструкций. 920003 — свой пользователь (мутирует данные).
// Проверяем поведение (подписи, поля, превью, сохранение/повторное открытие), не эстетику.
const USER = 920_003;
test.describe.configure({ mode: "serial" });

const TECH = /reps_sets|time_sets|max_effort|prescription|source_type|undefined|NaN|\.00\b/;

async function saveItemAndWorkout(page: Page) {
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  await expect(page.getByTestId("workout-item")).toHaveCount(1);
}

test("создание: пустое название блокирует шаг, протоколы объяснены словами", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, USER);
  await page.getByRole("button", { name: "Создать", exact: true }).click();
  await expect(page.getByRole("button", { name: "Создать и добавить упражнения" })).toBeDisabled();
  await page.getByRole("textbox").fill("UX проверка");
  await expect(page.getByRole("button", { name: "Создать и добавить упражнения" })).toBeEnabled();
  await page.getByRole("button", { name: "Создать и добавить упражнения" }).click();
  await page.getByRole("button", { name: "+ Добавить упражнение" }).click();
  await page.locator(".ux-pick").first().click();

  const kinds = page.getByRole("radiogroup", { name: "Тип работы" });
  await expect(kinds).toContainText("Несколько подходов с заданным количеством повторений");
  await expect(kinds).toContainText("Несколько подходов на время");
  await expect(kinds).toContainText("Несколько попыток на максимум");
  await expect(kinds).toContainText("Работа и отдых по таймеру");
  await expect(page.locator("body")).not.toContainText(TECH);
  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});

test("reps: явные подписи, −/+ и ввод, превью = то, что сохранится и открывается снова", async ({ page }) => {
  const { apiFailures } = await openAppAs(page, USER);
  await page.getByTestId("my-workout-card").filter({ hasText: "UX проверка" }).click();
  await page.getByRole("button", { name: "+ Добавить упражнение" }).click();
  await page.locator(".ux-pick").first().click();

  const fields = page.getByTestId("protocol-fields");
  await expect(fields.getByRole("textbox", { name: "Подходы", exact: true })).toHaveValue("3");
  await expect(fields.getByRole("textbox", { name: "Повторения в подходе", exact: true })).toHaveValue("10");
  await expect(fields.getByRole("textbox", { name: "Отдых между подходами", exact: true })).toHaveValue("01:00");
  await fields.getByRole("button", { name: "Меньше: Подходы" }).click(); // 2
  await fields.getByRole("textbox", { name: "Повторения в подходе", exact: true }).fill("8");
  await fields.getByRole("button", { name: "Больше: Отдых между подходами" }).click(); // +15 c
  const preview = page.getByTestId("protocol-preview");
  await expect(preview).toContainText("2 × 8 повторений");
  await expect(preview).toContainText("Отдых между подходами 1:15");

  // Смена типа и возврат не теряют введённое.
  await page.getByRole("radio", { name: /^Время/ }).click();
  await expect(fields.getByRole("textbox", { name: "Время подхода", exact: true })).toBeVisible();
  await expect(fields.getByRole("textbox", { name: "Повторения в подходе", exact: true })).toHaveCount(0);
  await page.getByRole("radio", { name: /^Повторения/ }).click();
  await expect(fields.getByRole("textbox", { name: "Повторения в подходе", exact: true })).toHaveValue("8");

  // Невалидное значение блокирует кнопку и объясняет причину.
  await fields.getByRole("textbox", { name: "Подходы", exact: true }).fill("");
  await expect(page.getByRole("button", { name: "Добавить", exact: true })).toBeDisabled();
  await expect(page.getByRole("alert")).toContainText("Укажите количество подходов");
  await fields.getByRole("textbox", { name: "Подходы", exact: true }).fill("2");

  await saveItemAndWorkout(page);
  const item = page.getByTestId("workout-item");
  await expect(item).toContainText("2 × 8 повторений");
  await expect(item).toContainText("Отдых между подходами 1:15");
  await expect(page.getByTestId("workout-items")).not.toContainText(TECH);

  // Повторное открытие: те же значения.
  await item.getByRole("button", { name: /^Изменить:/ }).click();
  await expect(fields.getByRole("textbox", { name: "Подходы", exact: true })).toHaveValue("2");
  await expect(fields.getByRole("textbox", { name: "Повторения в подходе", exact: true })).toHaveValue("8");
  await expect(fields.getByRole("textbox", { name: "Отдых между подходами", exact: true })).toHaveValue("01:15");
  expect(apiFailures).toEqual([]);
});

test("time, max, interval: свои подписи, превью, сохранение", async ({ page }) => {
  const { apiFailures } = await openAppAs(page, USER);
  await page.getByTestId("my-workout-card").filter({ hasText: "UX проверка" }).click();
  const fields = page.getByTestId("protocol-fields");
  const preview = page.getByTestId("protocol-preview");

  await expect(page.getByTestId("workout-item")).toHaveCount(1); // reps из предыдущего теста
  let count = 1;
  async function addWith(kind: RegExp, act: () => Promise<void>, expected: string[]) {
    await page.getByRole("button", { name: "+ Добавить упражнение" }).click();
    await page.locator(".ux-pick").first().click();
    await page.getByRole("radio", { name: kind }).click();
    await act();
    for (const text of expected) await expect(preview).toContainText(text);
    await page.getByRole("button", { name: "Добавить", exact: true }).click();
    count += 1;
    await expect(page.getByTestId("workout-item")).toHaveCount(count);
    await expect(page.getByTestId("workout-item").last()).toContainText(expected[0]);
  }

  await addWith(/^Время/, async () => {
    await expect(fields.getByRole("textbox", { name: "Время подхода", exact: true })).toHaveValue("00:30");
    await fields.getByRole("textbox", { name: "Время подхода", exact: true }).fill("0:45");
  }, ["3 × 45 сек", "Отдых между подходами 1:00"]);

  await addWith(/^Максимум/, async () => {
    await expect(fields).toContainText("В каждой — максимум, цели нет");
    await expect(fields.getByRole("textbox", { name: "Повторения в подходе", exact: true })).toHaveCount(0);
    await fields.getByRole("textbox", { name: "Количество попыток", exact: true }).fill("2");
  }, ["2 попытки на максимум", "Отдых между попытками 3:00"]);

  await addWith(/^Интервалы/, async () => {
    await fields.getByRole("textbox", { name: "Общее время", exact: true }).fill("6:00");
  }, ["6 раундов", "30 сек работа / 30 сек отдых · всего 6:00"]);

  await expect(page.getByTestId("workout-items")).not.toContainText(TECH);
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByTestId("my-workouts")).toBeVisible();
  expect(apiFailures).toEqual([]);
});
