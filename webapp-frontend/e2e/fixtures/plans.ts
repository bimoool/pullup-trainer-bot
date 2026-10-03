import { expect, type Locator, type Page } from "@playwright/test";

// «Планы» (#286 B): действия строки дня и плана живут в нижнем листе за кнопкой «⋯» —
// специ сначала открывают лист, потом выбирают пункт (смысл проверок не меняется).

export type RowAction = "Перенести" | "Редактировать тренировку" | "Убрать из плана";
export type PlanAction = "Скопировать неделю" | "Убрать курс из плана";

/** Открыть лист «⋯» строки (первой, либо строки с заданным названием) и нажать пункт. */
export async function pickRowAction(page: Page, action: RowAction, title?: string | RegExp): Promise<void> {
  const row = title === undefined
    ? page.getByTestId("plans-row-more").first()
    : page.locator('[data-testid="plans-row"]').filter({ hasText: title }).getByTestId("plans-row-more");
  await row.click();
  await page.getByTestId("plans-row-sheet").getByRole("button", { name: action, exact: true }).click();
}

/** Открыть лист «⋯» и нажать пункт (#288): «Скопировать неделю N → N+1» — в листе плана («Текущий план», «⋯» в шапке
 * карточки), «Убрать курс из плана» — в листе курса (внутри scope — карточки курса, иначе первой на экране). */
export async function pickPlanAction(page: Page, action: PlanAction, scope?: Locator): Promise<void> {
  if (action === "Скопировать неделю") {
    await page.getByTestId("plans-card-more").click();
    await page.getByTestId("plans-plan-sheet").getByRole("button", { name: /^Скопировать неделю \d+ → \d+$/ }).click();
    return;
  }
  await (scope ?? page).getByTestId("plans-plan-more").first().click();
  await page.getByTestId("plans-plan-sheet").getByRole("button", { name: action, exact: true }).click();
}

/** Кнопка «Начать» строки/блока «Сегодня» — её имя «Начать: <название>[, день]» (#288); на предэкране — просто «Начать». */
export const PLAN_START = /^Начать: /;

/** Лист закрыт (ни строки, ни плана). */
export async function expectNoPlansSheet(page: Page): Promise<void> {
  await expect(page.getByRole("dialog")).toHaveCount(0);
}

/** #288 — «сегодня» пользователя на сервере (`plan.today`, часовой пояс пользователя), а не часы машины с Playwright.
 * Вызвать ДО openAppAs/goto; `today()` ждёт первый ответ GET /api/v2/plan. */
export function watchServerPlanToday(page: Page): { today: () => Promise<string>; weekdayIndex: () => Promise<number> } {
  const first = new Promise<string>((resolve) => {
    page.on("response", async (response) => {
      if (!/\/api\/v2\/plan(\?|$)/.test(response.url()) || response.request().method() !== "GET") {
        return;
      }
      try {
        const body = await response.json();
        if (body?.plan?.today) {
          resolve(body.plan.today as string);
        }
      } catch {
        // не JSON — не наш ответ
      }
    });
  });
  const weekdayOf = (iso: string) => (new Date(`${iso}T00:00:00Z`).getUTCDay() + 6) % 7; // 0 = пн … 6 = вс
  return { today: () => first, weekdayIndex: async () => weekdayOf(await first) };
}

/** Подменить ответ GET /api/v2/plan (`mutate` правит JSON). Ошибки позднего запроса (страница уже закрыта) глотаем —
 * иначе обработчик, пойманный на разборке теста, роняет прогон «вне теста». */
export async function mutatePlanResponse(page: Page, mutate: (body: any) => void): Promise<void> {
  await page.route(/\/api\/v2\/plan(\?|$)/, async (route) => {
    try {
      if (route.request().method() !== "GET") {
        await route.continue();
        return;
      }
      const response = await route.fetch();
      const body = await response.json();
      mutate(body);
      await route.fulfill({ response, json: body });
    } catch {
      // страница/контекст закрыты — ответ уже не нужен
    }
  });
}

/** Подменить `today` в ответах GET /api/v2/plan (null — не трогать), чтобы проверить «Сегодня» независимо от часов устройства. */
export async function overridePlanToday(page: Page, today: () => string | null): Promise<void> {
  await mutatePlanResponse(page, (body) => {
    const forced = today();
    if (body?.plan && forced !== null) {
      body.plan.today = forced;
    }
  });
}
