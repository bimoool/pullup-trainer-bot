import { expect, test, type Locator, type Page } from "@playwright/test";

import { noWakeLock } from "../fixtures/builderFlow";
import { openAppAs } from "../fixtures/setup";

// Редактор тренировки при экранной клавиатуре (issue #250). Гоняется проектами
// keyboard-320/390 (см. playwright.config.ts). Клавиатура = уменьшение высоты
// окна (как в Telegram WebView). 920004 — свой посеянный пользователь
// (home_workouts); сценарий ничего не сохраняет, повторный прогон безопасен.
const TELEGRAM_ID = 920_004;
const KEYBOARD_HEIGHT = 380;

async function expectNoHorizontalOverflow(page: Page, where: string) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth, `горизонтальный overflow: ${where}`).toBeLessThanOrEqual(clientWidth);
}

// Элемент целиком в окне, не перекрыт нижней навигацией и другими элементами.
async function expectReachable(page: Page, target: Locator, what: string) {
  await target.scrollIntoViewIfNeeded();
  const box = await target.boundingBox();
  const vh = page.viewportSize()!.height;
  const tabbar = await page.locator(".bottom-tabbar").boundingBox();
  expect(box, `нет бокса: ${what}`).not.toBeNull();
  expect(box!.y, `${what} выше окна`).toBeGreaterThanOrEqual(0);
  expect(box!.y + box!.height, `${what} ниже окна`).toBeLessThanOrEqual(vh);
  if (tabbar) {
    expect(box!.y + box!.height, `${what} перекрыт навигацией`).toBeLessThanOrEqual(tabbar.y + 1);
  }
  const hit = await target.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return top === el || el.contains(top);
  });
  expect(hit, `${what} перекрыт другим элементом`).toBe(true);
}

test("редактор: поля и кнопки достижимы при клавиатуре, после возврата нет смещений", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);
  const { width, height: fullHeight } = page.viewportSize()!;

  await page.getByTestId("my-workout-card").filter({ hasText: "Пустая заготовка" }).click();
  await page.getByRole("button", { name: "Изменить", exact: true }).click();
  const name = page.getByRole("textbox");
  await expect(name).toHaveValue("Пустая заготовка");

  // Название + «Сохранить» при клавиатуре.
  await name.focus();
  await page.setViewportSize({ width, height: KEYBOARD_HEIGHT });
  await expectReachable(page, name, "поле названия");
  await expectReachable(page, page.getByRole("button", { name: "Сохранить", exact: true }), "«Сохранить»");
  await expectReachable(page, page.getByRole("button", { name: "+ Добавить упражнение" }), "«Добавить упражнение»");
  await expectNoHorizontalOverflow(page, "редактор с клавиатурой");

  // Протокол: поля и «Добавить» при клавиатуре.
  await page.setViewportSize({ width, height: fullHeight });
  await page.getByRole("button", { name: "+ Добавить упражнение" }).click();
  await page.locator(".ux-pick").first().click();
  const fields = page.getByTestId("protocol-fields");
  const sets = fields.getByRole("textbox", { name: "Подходы", exact: true });
  const reps = fields.getByRole("textbox", { name: "Повторения в подходе", exact: true });
  await sets.focus();
  await page.setViewportSize({ width, height: KEYBOARD_HEIGHT });
  await expectReachable(page, sets, "«Подходы»");
  await reps.focus();
  await expectReachable(page, reps, "«Повторения в подходе»");
  const submit = page.getByRole("button", { name: "Добавить", exact: true });
  await expectReachable(page, submit, "«Добавить»");
  await expect(submit).toBeEnabled();
  await expectNoHorizontalOverflow(page, "протокол с клавиатурой");

  // Восстановление окна: без горизонтального смещения/overflow, верх экрана достижим.
  await page.setViewportSize({ width, height: fullHeight });
  await page.evaluate(() => window.scrollTo(0, 0));
  expect(await page.evaluate(() => window.scrollX)).toBe(0);
  await expectNoHorizontalOverflow(page, "протокол после клавиатуры");
  const label = await page.getByText("Подходы", { exact: true }).first().boundingBox();
  expect(label!.y).toBeGreaterThanOrEqual(0);
  await page.getByRole("button", { name: "Отмена" }).click();
  await expectNoHorizontalOverflow(page, "редактор после клавиатуры");

  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});
