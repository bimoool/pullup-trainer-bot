import { expect, test, type Page } from "@playwright/test";

import { buildInitData, getTestBotToken } from "../fixtures/initData";
import { openAppAs } from "../fixtures/setup";

/**
 * Аудит staging 7500c37 (живой Telegram Web), три пути:
 *  1. Упражнение, добавленное в план без параметров, стартовало заглушкой «Максимум · 3 попытки», а пред-экран был
 *     пустым. Теперь «+ Добавить упражнение» спрашивает «Как выполнять» и сохраняет выбор (своя тренировка из одного
 *     упражнения, без миграции); старая строка «только упражнение» перед стартом честно говорит «Параметры не заданы»
 *     и даёт выбор — задать подходы или явно начать «3 подхода на максимум». Сид: plan_week_add_exercise 931001–931003.
 *  2. 320 px: поле результата в фазе «Пошёл» не должно прятаться под липким транспортом; в фокусе транспорт отлипает
 *     (экранная клавиатура). Сид: live_engine 931004.
 *  3. Свободная запись по готовой тренировке каталога: удалять её нельзя (правило прежнее), но Журнал объясняет
 *     почему, а не прячет «Удалить» молча. Сид: journal_catalog_session 931005.
 */
test.setTimeout(90_000);
test.use({ viewport: { width: 320, height: 640 }, isMobile: true, hasTouch: true });

const headers = (telegramId: number) => ({
  "X-Telegram-Init-Data": buildInitData({ id: telegramId, firstName: "E2E" }, getTestBotToken()),
});

type PlanItem = { id: number; exercise_id: number; complex_id: number | null; complex_name: string | null; program_inclusion_id: number | null; status?: string };

async function planItems(page: Page, telegramId: number): Promise<PlanItem[]> {
  const response = await page.request.get("/api/v2/plan", { headers: headers(telegramId) });
  expect(response.ok()).toBe(true);
  return ((await response.json()).plan?.plan_items ?? []) as PlanItem[];
}

async function exerciseId(page: Page, telegramId: number, name: string): Promise<number> {
  const response = await page.request.get("/api/v2/exercises", { headers: headers(telegramId) });
  const found = ((await response.json()).exercises as { id: number; name: string }[]).find((e) => e.name === name);
  expect(found, `упражнение «${name}» в библиотеке`).toBeTruthy();
  return found!.id;
}

/** Старая строка «только упражнение» (как до исправления): тот же публичный POST /plan-items, что слал старый клиент. */
async function addLegacyExerciseItem(page: Page, telegramId: number, name: string): Promise<number> {
  await planItems(page, telegramId); // материализует текущую неделю
  const response = await page.request.post("/api/v2/plan-items", {
    headers: headers(telegramId),
    data: { exercise_id: await exerciseId(page, telegramId, name), count_per_week: 1, day_of_week: null },
  });
  expect(response.ok()).toBe(true);
  return (await response.json()).id as number;
}

async function startFromPlans(page: Page, rowName: string) {
  await page.getByRole("button", { name: "Планы" }).click();
  const start = page.getByRole("button", { name: `Начать: ${rowName}` }).first();
  await start.scrollIntoViewIfNeeded();
  await start.click();
}

test("1a: «+ Добавить упражнение» спрашивает «Как выполнять», и пред-экран показывает выбранные параметры", async ({ page }) => {
  const telegramId = 931_001;
  const { apiFailures } = await openAppAs(page, telegramId);
  await page.getByRole("button", { name: "Планы" }).click();
  const add = page.getByRole("button", { name: "+ Добавить упражнение" }).first();
  await add.scrollIntoViewIfNeeded();
  await add.click();
  const form = page.getByTestId("plan-add-exercise-form");
  await form.getByRole("button", { name: "Отжимания", exact: true }).click();
  await form.getByRole("button", { name: "Далее" }).click();
  // Шаг «Как выполнять»: без него упражнение раньше уходило в план без параметров.
  await expect(form.getByRole("radiogroup", { name: "Тип работы" })).toBeVisible();
  await expect(form.getByTestId("protocol-preview")).toContainText("3 × 10");
  await form.getByRole("button", { name: "Добавить в план" }).click();
  await expect(form).toHaveCount(0, { timeout: 10_000 });

  const items = (await planItems(page, telegramId)).filter((item) => item.program_inclusion_id === null && item.status !== "removed");
  expect(items.map((item) => item.complex_name)).toEqual(["Отжимания"]);
  expect(items[0].complex_id, "в плане — тренировка с протоколом, не строка «только упражнение»").not.toBeNull();

  await startFromPlans(page, "Отжимания");
  await expect(page.getByTestId("session-pre-items")).toContainText("Отжимания");
  await expect(page.getByTestId("session-pre-items")).toContainText("3 × 10");
  await expect(page.getByTestId("session-pre-params-missing")).toHaveCount(0);
  expect(apiFailures).toEqual([]);
});

test("1b: старая строка без параметров — «Параметры не заданы», выбор «Задать подходы» сохраняет и стартует по ним", async ({ page }) => {
  const telegramId = 931_002;
  const { apiFailures } = await openAppAs(page, telegramId);
  const legacyId = await addLegacyExerciseItem(page, telegramId, "Отжимания");
  const starts: unknown[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && /\/api\/v2\/sessions\/live$/.test(request.url())) {
      starts.push(request.postDataJSON());
    }
  });

  await startFromPlans(page, "Отжимания");
  const missing = page.getByTestId("session-pre-params-missing");
  await expect(missing).toContainText("Параметры не заданы");
  await expect(missing).toContainText("3 подхода на максимум");
  await expect(page.getByRole("button", { name: "Начать", exact: true })).toHaveCount(0); // нет молчаливого старта
  expect(starts).toEqual([]);
  // 320 px: подписи кнопок выбора не обрезаются многоточием (живая проверка 352fd15 — «Задать подходы и повто…»).
  for (const testId of ["session-pre-set-params", "session-pre-start-max"]) {
    const clipped = await page.getByTestId(testId).evaluate((button) =>
      [button, ...button.querySelectorAll("*")].some((element) => element.scrollWidth > element.clientWidth + 1));
    expect(clipped, `подпись ${testId} обрезана`).toBe(false);
  }

  await page.getByTestId("session-pre-set-params").click();
  await expect(page.getByTestId("session-pre-params-form")).toBeVisible();
  await page.getByRole("button", { name: "Сохранить и начать" }).click();
  await expect(page.getByTestId("engine-phase")).toBeVisible({ timeout: 15_000 });
  // Стартовала тренировка с подходами на повторения, а не тест на максимум.
  await expect(page.locator(".live-screen")).toContainText("Цель: 10 повт.");
  await expect(page.locator(".live-screen")).not.toContainText("Попытка");

  const items = await planItems(page, telegramId);
  expect(items.some((item) => item.id === legacyId && item.status !== "removed"), "старая строка убрана из плана").toBe(false);
  expect(items.some((item) => item.complex_name === "Отжимания" && item.complex_id !== null)).toBe(true);
  expect(starts).toHaveLength(1);
  expect(apiFailures).toEqual([]);
});

test("1c: старая строка без параметров — явный выбор «3 подхода на максимум» стартует как раньше", async ({ page }) => {
  const telegramId = 931_003;
  const { apiFailures } = await openAppAs(page, telegramId);
  await addLegacyExerciseItem(page, telegramId, "Отжимания");
  await startFromPlans(page, "Отжимания");
  await page.getByTestId("session-pre-start-max").click();
  await expect(page.getByTestId("engine-phase")).toBeVisible({ timeout: 15_000 });
  await expect(page.locator(".live-screen")).toContainText("Попытка 1/3");
  expect(apiFailures).toEqual([]);
});

test.describe("320×480", () => {
  test.use({ viewport: { width: 320, height: 480 }, isMobile: true, hasTouch: true });

  test("2: поле результата в фазе «Пошёл» видно и не под транспортом; в фокусе транспорт отлипает", async ({ page }) => {
    const { apiFailures } = await openAppAs(page, 931_004);
    await page.getByRole("button", { name: "Планы" }).click();
    const group = page.locator(".plan-week-day-group").filter({ hasText: /^Движок: подходы/ });
    await group.getByRole("button", { name: /^Начать: / }).first().click();
    await page.getByRole("button", { name: "Начать", exact: true }).click();
    await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл", { timeout: 10_000 });

    const input = page.getByLabel("Результат подхода");
    // Без прокрутки пользователем: поле в окне и центр поля — само поле, не липкая панель.
    await expect(input).toBeInViewport();
    const inputOnTop = await input.evaluate((element) => {
      const box = element.getBoundingClientRect();
      const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
      return hit !== null && (element === hit || element.contains(hit));
    });
    expect(inputOnTop, "поле результата перекрыто нижней панелью").toBe(true);
    await expect(page.getByTestId("engine-submit")).toBeInViewport();

    await input.focus();
    await expect(page.locator(".live-screen")).toHaveAttribute("data-field-focus", "true");
    await expect(page.locator(".live-transport")).toHaveCSS("position", "static");
    await input.fill("5");
    await page.getByTestId("engine-submit").click();
    await expect(page.getByTestId("engine-phase")).toHaveText("Отдых", { timeout: 10_000 });
    expect(apiFailures).toEqual([]);
  });
});

test("3: запись каталожной тренировки — в Журнале причина, почему удалить нельзя, вместо пропавшей кнопки", async ({ page }) => {
  const { apiFailures } = await openAppAs(page, 931_005);
  await page.getByRole("button", { name: "Журнал" }).click();
  const entry = page.getByText("Каталог e2e 931005").first();
  await entry.scrollIntoViewIfNeeded();
  await entry.click();
  const sheet = page.getByTestId("journal-entry-sheet");
  await expect(sheet).toBeVisible();
  await expect(sheet.getByTestId("journal-sheet-delete")).toHaveCount(0);
  await expect(sheet.getByTestId("journal-sheet-delete-reason")).toContainText("готовой тренировки из каталога");
  await sheet.getByTestId("journal-sheet-open").click();
  await expect(page.getByTestId("journal-delete-reason")).toContainText("готовой тренировки из каталога");
  expect(apiFailures).toEqual([]);
});
