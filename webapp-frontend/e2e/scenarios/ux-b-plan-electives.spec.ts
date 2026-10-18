import { expect, test, type Page } from "@playwright/test";

import { mockPlanContract } from "../fixtures/contractMock";
import { openAppAs } from "../fixtures/setup";

// Исполнитель B (ux-ref-20261018): путь «карточка курса → Открыть мой план → строки А/Б → старт» и
// факультативы (UX-33). Сиды (scripts/e2e_seed.py, см. e2e_seed_all.sh):
//   ux_b_no_course 940201 — свежий профиль, курса нет;
//   ux_b_legacy    940202 — форма подключения владельца (CONTRACT_A_B §5): 3 занятия в неделю, первое выполнено сегодня;
//   ux_b_legacy    940203 — то же для факультативов (свой пользователь: тест пишет факультативы);
//   ux_b_legacy    940204 — то же для скриншотов (только чтение).
// До интеграции ветки A поля контракта достраивает fixtures/contractMock.ts поверх настоящего ответа стенда
// (E2E_REAL_CONTRACT=1 — без достройки, против настоящего бэкенда A).
// Текущий день недели при прогоне разный, поэтому «рано» и «не уместится» принимаются как равноправные причины.
const FRESH_ID = 940_201;
const LEGACY_ID = 940_202;
const ELECTIVE_ID = 940_203;

const LEGACY_SCHEDULE = {
  sessions_per_week: 3, source: "catalogue" as const, is_legacy: true, min_days_between_starts: 3, weekly_capacity: 2,
};
const BLOCKED_LABEL = /Доступно с \d+ |Не уместится на этой неделе/;

async function openPlans(page: Page) {
  await page.getByRole("button", { name: "Планы" }).click();
  await expect(page.getByTestId("plans-now-card")).toBeVisible();
}

test.describe("ux-b: план и факультативы", () => {
  test.afterEach(async ({ page }) => {
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });

  test("(a) свежий профиль: курс → «Открыть мой план» → строки А/Б → старт", async ({ page }) => {
    await mockPlanContract(page);
    const { apiFailures } = await openAppAs(page, FRESH_ID);

    await page.locator(".program-card-button").first().click();
    await page.getByRole("button", { name: "Добавить в план" }).click();
    // UX-06: после добавления — следующий шаг, не тупик «В плане».
    const openPlan = page.getByTestId("program-open-plan");
    await expect(openPlan).toBeVisible();
    await expect(page.getByTestId("program-included-card")).toBeVisible();
    await openPlan.click();

    await expect(page.getByTestId("plans-now-card")).toBeVisible();
    const rows = page.getByTestId("plans-row");
    await expect(rows).toHaveCount(2);
    // UX-08/09: строки названы по занятию курса, одно написание «А»/«Б».
    await expect(rows.nth(0).getByTestId("plans-row-variant")).toHaveText("Объём (А) · занятие 1 из 2");
    await expect(rows.nth(1).getByTestId("plans-row-variant")).toHaveText("Сила (Б) · занятие 2 из 2");
    await expect(page.getByTestId("plans-row-variant").filter({ hasText: /[AB]\b/ })).toHaveCount(0);

    // Доступное занятие стартует: «Начать» есть ровно у разрешённых строк.
    const start = rows.nth(0).getByRole("button", { name: /^Начать:/ });
    await expect(start).toBeVisible();
    await start.click();
    // Первый старт курса: либо пред-экран с «Начать», либо (нет теста 1RM) форма недостающих данных курса —
    // оба — настоящий следующий шаг, не экран «нельзя».
    await expect(
      page.getByTestId("course-setup-required").or(page.getByRole("button", { name: "Начать", exact: true })),
    ).toBeVisible();
    await expect(page.getByText("Перейти в обычную")).toHaveCount(0);
    expect(apiFailures).toEqual([]);
  });

  test("(b) устаревшее подключение: «1 из 3», пояснение, заблокированные строки говорят когда", async ({ page }) => {
    await mockPlanContract(page, { schedule: LEGACY_SCHEDULE });
    const { apiFailures } = await openAppAs(page, LEGACY_ID);
    await openPlans(page);

    await expect(page.getByTestId("plans-now-progress")).toHaveText("На этой неделе: 1 из 3");
    const schedule = page.getByTestId("plans-now-card").getByTestId("course-schedule");
    await expect(schedule.getByTestId("course-schedule-headline")).toHaveText("Расписание вашей версии курса: 3 занятия в неделю");
    await expect(schedule.getByTestId("course-schedule-consequence")).toContainText("Не все занятия уместятся");
    // Нет кнопки «перейти на 2» (вне объёма кампании).
    await expect(page.getByText(/Перейти на 2/)).toHaveCount(0);

    const rows = page.getByTestId("plans-row");
    await expect(rows).toHaveCount(3);
    // Первое выполнено, второе и третье не стартуют и говорят почему/когда — ни одной кнопки «Начать».
    await expect(rows.nth(0).getByTestId("plans-row-state")).toHaveText("Выполнено");
    for (const index of [1, 2]) {
      await expect(rows.nth(index).getByTestId("plans-row-state")).toHaveText(BLOCKED_LABEL);
      await expect(rows.nth(index).getByRole("button", { name: /^Начать:/ })).toHaveCount(0);
    }
    await expect(rows.nth(0).getByTestId("plans-row-variant")).toHaveText(/^Объём \(А\) · занятие 1 из 3$/);
    await expect(rows.nth(1).getByTestId("plans-row-variant")).toHaveText(/^Сила \(Б\) · занятие 2 из 3$/);
    expect(apiFailures).toEqual([]);
  });

  test("(c) факультатив: из карточки и из состояния «Сегодня отдых», отправка, счётчик, лимит", async ({ page }) => {
    await mockPlanContract(page, { schedule: LEGACY_SCHEDULE });
    const { apiFailures } = await openAppAs(page, ELECTIVE_ID);
    await openPlans(page);

    // Состояние отдыха в плане и строка на карточке курса — два входа в один экран.
    await expect(page.getByTestId("elective-rest-day")).toContainText("Сегодня отдых — можно факультатив");
    await expect(page.getByTestId("elective-counter")).toHaveText("Факультативы: 0 из 2 на этой неделе");
    await expect(page.getByTestId("elective-explanation")).toContainText("Бесплатно, до 2 в неделю");

    async function doElective(entry: "rest-day" | "card") {
      await page.getByTestId(entry === "rest-day" ? "elective-rest-day-open" : "elective-open").click(); // касание 1
      await expect(page.getByText("Факультатив", { exact: true })).toBeVisible();
      // Касание 2: первый доступный формат (ротация без повтора — каждый раз другой).
      await page.locator("button.action-button").first().click();
      const total = page.getByLabel("Итого повторений");
      if (await total.count() > 0) {
        await total.fill("20");
      } else {
        const cells = page.getByLabel(/^Подход \d+/);
        const n = await cells.count();
        for (let k = 0; k < n; k += 1) {
          await cells.nth(k).fill("5");
        }
      }
      await page.getByRole("button", { name: "Записать факультатив" }).click();
      await expect(page.getByText("Факультатив записан")).toBeVisible();
      await page.getByRole("button", { name: "Готово" }).click();
      await expect(page.getByTestId("plans-now-card")).toBeVisible();
    }

    await doElective("rest-day");
    await expect(page.getByTestId("elective-counter")).toHaveText("Факультативы: 1 из 2 на этой неделе");
    await doElective("card");
    await expect(page.getByTestId("elective-counter")).toHaveText("Факультативы: 2 из 2 на этой неделе");

    // Лимит: явный текст вместо скрытой кнопки.
    await expect(page.getByTestId("elective-open")).toHaveCount(0);
    await expect(page.getByTestId("elective-limit").first()).toContainText("Лимит факультативов");

    // Журнал показывает факультатив.
    await page.getByRole("button", { name: "Журнал", exact: true }).click();
    await expect(page.getByText(/акультатив/i).first()).toBeVisible();
    expect(apiFailures).toEqual([]);
  });

  test("Главная: «+» → «Факультатив» открывает экран факультатива", async ({ page }) => {
    await mockPlanContract(page);
    const { apiFailures } = await openAppAs(page, 940_204);
    await page.getByTestId("home-plus").click();
    await page.getByTestId("home-sheet-elective").click();
    await expect(page.getByText(/акультатив/i).first()).toBeVisible();
    expect(apiFailures).toEqual([]);
  });
});
