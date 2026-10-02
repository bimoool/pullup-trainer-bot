import { expect, type Page } from "@playwright/test";

/** Общие шаги сценариев Builder-тренировки (R1/R2): открыть Workout с
 * карточки "Планов", пройти подходы блока. */

export async function startWorkout(page: Page, title: string) {
  // на деталях (курс/тренировка) нижней навигации нет — сначала «назад» на вкладку
  const tabbar = page.locator(".bottom-tabbar");
  // дождаться первого рендера: либо навигация, либо «назад» (иначе isVisible() читает ещё пустую страницу)
  await expect(tabbar.or(page.getByRole("button", { name: /Назад/ }).first())).toBeVisible();
  if (!(await tabbar.isVisible())) {
    await page.getByRole("button", { name: /Назад/ }).first().click();
  }
  await page.getByRole("button", { name: "Планы" }).click();
  const group = page.locator(".plan-week-day-group").filter({ has: page.getByText(title, { exact: false }) })
    .filter({ hasText: new RegExp(`^${title}`) });
  await group.getByRole("button", { name: /^Начать: / }).click();
  await page.getByRole("button", { name: "Начать", exact: true }).click(); // SessionPreScreen
  await expect(page.getByText("Живая тренировка")).toBeVisible();
}

/** Клик + ожидание ответа сервера: повторный тап во время уже идущего
 * запроса приложение намеренно отбрасывает (guardedAction). */
export async function clickAndSync(page: Page, name: string, urlPart: string) {
  const response = page.waitForResponse((r) => r.url().includes(urlPart) && r.status() === 200);
  await page.getByRole("button", { name, exact: true }).click();
  await response;
}

/** Один обычный блок целиком: подходы с отдыхом; после последнего подхода
 * не трогает ничего. */
export async function playSets(page: Page, values: string[], rest = true) {
  for (let i = 0; i < values.length; i += 1) {
    await clickAndSync(page, "Готов", "/phase/next");
    await expect(page.getByText("Пошёл")).toBeVisible();
    await page.getByLabel(/Результат|Секунды|Повторений/).fill(values[i]);
    await clickAndSync(page, "Готово", "/sets:batch");
    if (i < values.length - 1 && rest) {
      await clickAndSync(page, "Пропустить отдых", "/phase/next");
    }
  }
}

// Headless Chromium не даёт Wake Lock — шум окружения, не баг приложения.
export const noWakeLock = (errors: string[]) => errors.filter((e) => !e.includes("Wake Lock"));
