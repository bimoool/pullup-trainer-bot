import { expect, type Page } from "@playwright/test";

/** Общие шаги сценариев Builder-тренировки (R1/R2): открыть Workout с
 * карточки "Планов", пройти подходы блока. */

export async function startWorkout(page: Page, title: string) {
  // на деталях (курс/тренировка) нижней навигации нет — сначала «назад» на вкладку
  const tabbar = page.locator(".bottom-tabbar");
  // дождаться первого рендера: либо навигация, либо «назад» (иначе isVisible() читает ещё пустую страницу)
  await expect(tabbar.or(page.getByRole("button", { name: /Назад/ }).first()).first()).toBeVisible();
  if (!(await tabbar.isVisible())) {
    await page.getByRole("button", { name: /Назад/ }).first().click();
  }
  await page.getByRole("button", { name: "Планы" }).click();
  const group = page.locator(".plan-week-day-group").filter({ has: page.getByText(title, { exact: false }) })
    .filter({ hasText: new RegExp(`^${title}`) });
  // #304: одна строка плана = одно занятие — у «N раз в неделю» несколько строк; берём первое занятие.
  await group.getByRole("button", { name: /^Начать: / }).first().click();
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

/** issue #306 — Live Engine v2: подход за подходом без «Готов»/«Пропустить отдых». Ожидание (подготовка/отдых)
 * сокращается необязательным «Начать сейчас» (skip_wait) — сам переход по дедлайну проверяет
 * live-engine-v2.spec.ts реальным временем. После последнего подхода ничего не трогает. */
export async function playSetsV2(page: Page, values: string[]) {
  for (const value of values) {
    const phase = page.getByTestId("engine-phase");
    await expect(phase).toHaveText(/Приготовься|Отдых|Пошёл/);
    if ((await phase.textContent())?.trim() !== "Пошёл") {
      await page.getByTestId("engine-skip").click();
    }
    await expect(phase).toHaveText("Пошёл");
    await page.getByLabel("Результат подхода").fill(value);
    await page.getByTestId("engine-submit").click();
    await expect(page.getByTestId("engine-pending")).toHaveCount(0, { timeout: 10_000 });
  }
}

/** issue #306 — завершить тренировку v2: экран «Тренировка завершена» → «Сохранить» (или досрочно —
 * «Завершить» → «Сохранить и завершить»). */
export async function finishV2(page: Page, { early = false }: { early?: boolean } = {}) {
  const completed = page.waitForResponse((r) => r.url().includes("/complete") && r.status() === 200);
  if (early) {
    await page.getByTestId("engine-finish").click();
    await page.getByTestId("engine-finish-confirm").click();
  } else {
    await expect(page.getByTestId("engine-complete")).toBeVisible();
    await page.getByTestId("engine-save").click();
  }
  await completed;
}

/** issue #306 — подход «на максимум по времени» (секундомер): «Стоп» → поле с измеренным → своё значение → «Готово». */
export async function logMaxTimeV2(page: Page, value: string) {
  const phase = page.getByTestId("engine-phase");
  await expect(phase).toHaveText(/Приготовься|Отдых|Пошёл/);
  if ((await phase.textContent())?.trim() !== "Пошёл") {
    await page.getByTestId("engine-skip").click();
  }
  await expect(phase).toHaveText("Пошёл");
  await page.getByTestId("engine-stop").click();
  await expect(phase).toHaveText("Результат");
  await page.getByLabel("Результат подхода").fill(value);
  await page.getByTestId("engine-submit").click();
}

/** issue #306 — подход на время: «Стоп» записывает измеренные секунды (цель — по дедлайну сама). */
export async function stopTimedSetV2(page: Page) {
  const phase = page.getByTestId("engine-phase");
  await expect(phase).toHaveText(/Приготовься|Отдых|Пошёл/);
  if ((await phase.textContent())?.trim() !== "Пошёл") {
    await page.getByTestId("engine-skip").click();
  }
  await expect(phase).toHaveText("Пошёл");
  await page.getByTestId("engine-stop").click();
  await expect(phase).not.toHaveText("Пошёл");
}
