// Journey regression for #301: «Подтягивания» weeks 2+ must not look empty («0 из 0») after week 1.
//
// RUN (clean DB at head, server on :8105 with BOT_TOKEN=audit-token, NO e2e_seed, NO per-user seeds):
//   su postgres -c "dropdb --if-exists pullup_j_e && createdb -O pullup pullup_j_e"
//   python -m alembic upgrade head      # DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:5432/pullup_j_e
//   python -m uvicorn app.web.main:app --host 127.0.0.1 --port 8105   # BOT_TOKEN=audit-token REDIS_URL=redis://localhost:6379/9
//   cd webapp-frontend/e2e && E2E_BASE_URL=http://127.0.0.1:8105 BOT_TOKEN=audit-token DATABASE_URL=<same as alembic> \
//     npx playwright test scenarios/fix-wave1/later-weeks.spec.ts --project=chromium
//   (this sandbox only: -c a config whose launchOptions.executablePath is /opt/pw-browsers/chromium-1194/chrome-linux/chrome)
//
// The user is created through the UI onboarding only. The course itself is made present by ensureCourseExists
// (no-op once the course ships with migrations).
import { expect, test, type Page } from "@playwright/test";

import { ensureCourseExists } from "../../fixtures/courseSeed";
import { buildInitData, getTestBotToken } from "../../fixtures/initData";
import { currentPlanWeek, planWeekLabel, relativePlanWeekNumber, type CalendarPlan } from "../../fixtures/planCalendar";
import { openAppAs, useLiveEngineV1 } from "../../fixtures/setup";

// issue #306: сценарий экрана движка v1 (сессии engine_version = 1) — новые старты здесь на v1.
useLiveEngineV1(test);

const TELEGRAM_ID = 7_900_000 + (Date.now() % 90_000);
const BASE_URL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:8001";

const nav = (page: Page, name: string) => page.getByRole("button", { name, exact: true });

async function onboard(page: Page) {
  await page.getByLabel("Сколько подтягиваний вышло?").fill("8");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByRole("button", { name: "Да" }).click();
  await page.getByRole("button", { name: "Продолжить" }).click();
  await page.getByLabel("Пол").selectOption({ label: "Мужской" });
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Дата рождения").fill("1992-04-15");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Часовой пояс").selectOption({ label: "Москва (UTC+3)" });
  await page.getByRole("button", { name: "Готово" }).click();
  await expect(page.getByText("Что потренируем сегодня?")).toBeVisible();
}

// issue #304 (AD-4, §6, J12): неделя курса — одна строка = одно занятие, будущие недели видимы И стартуемы
// (замок «Откроется <дата>» снят). #305 (V5.6 §1): новая инклюзия V5.6 — 2 занятия в неделю (A/B); каталог (3)
// и устаревшие инклюзии не меняются.
test("«Подтягивания»: четыре следующие недели видны с двумя занятиями V5.6 и кнопками старта", async ({ page }) => {
  const { apiFailures } = await openAppAs(page, TELEGRAM_ID, { allowedApiStatuses: [404] });
  page.on("dialog", (dialog) => void dialog.accept());
  await onboard(page);
  await ensureCourseExists(page.request, BASE_URL, TELEGRAM_ID);
  await page.reload();

  // Добавить курс: Главная → карточка → «Добавить в план» → «В плане».
  await page.locator(".program-card-button").filter({ hasText: "Подтягивания" }).first().click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await expect(page.getByRole("button", { name: "В плане" })).toBeVisible();
  await page.getByRole("button", { name: "Назад" }).first().click();
  await nav(page, "Планы").click();

  const readPlan = async () => {
    const response = await page.request.get(`${BASE_URL}/api/v2/plan`, {
      headers: { "X-Telegram-Init-Data": buildInitData({ id: TELEGRAM_ID, firstName: "E2E" }, getTestBotToken()) },
    });
    expect(response.ok()).toBe(true);
    return (await response.json()).plan as CalendarPlan & {
      plan_items: { plan_week_id: number; program_inclusion_id: number | null; count_per_week: number; occurrence_index: number | null }[];
      program_inclusions: { id: number; program_name: string; started_at: string }[];
    };
  };
  const initialPlan = await readPlan();
  const current = currentPlanWeek(initialPlan);
  const course = initialPlan.program_inclusions.find((inclusion) => inclusion.program_name === "Подтягивания");
  expect(course).toBeDefined();
  const courseStartDay = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Moscow" }).format(new Date(course!.started_at));
  const courseStart = new Date(`${courseStartDay}T00:00:00Z`);
  const courseMonday = courseStart.getTime() - ((courseStart.getUTCDay() + 6) % 7) * 86_400_000;
  expect(Date.parse(`${current.start_date}T00:00:00Z`)).toBe(courseMonday);
  expect(initialPlan.plan_items.filter((item) => item.plan_week_id === current.id && item.program_inclusion_id === course!.id)).toHaveLength(2);

  const rows = page.getByTestId("plans-row").filter({ hasText: "Подтягивания" });
  const assertCurrentWeekActionable = async () => {
    const plan = await readPlan();
    expect(currentPlanWeek(plan)).toEqual(current);
    await expect(page.getByTestId("plan-week-label")).toHaveText(planWeekLabel(current));
    await expect(page.getByTestId("plan-week-progress")).toContainText("Текущая неделя");
    await expect(page.getByTestId("plan-week-progress")).not.toContainText("0 из 0");
    await expect(rows).toHaveCount(2);
    await expect(page.getByRole("button", { name: /^Начать: Подтягивания/ }).first()).toBeVisible();
  };
  // Будущая неделя: занятия курса на месте, не пустое состояние, и их можно начать (§6).
  const assertFutureWeekHasCourse = async (offset: number) => {
    const weekNumber = relativePlanWeekNumber(current, offset);
    await expect(page.getByTestId("plan-week-label")).toContainText(`Неделя ${weekNumber} ·`);
    const plan = await readPlan();
    expect(currentPlanWeek(plan)).toEqual(current);
    const week = plan.plan_weeks.find((candidate) => candidate.week_number === weekNumber);
    expect(week).toBeDefined();
    expect(Date.parse(`${week!.start_date}T00:00:00Z`) - Date.parse(`${current.start_date}T00:00:00Z`)).toBe(offset * 7 * 86_400_000);
    expect((Date.parse(`${week!.start_date}T00:00:00Z`) - courseMonday) / (7 * 86_400_000) + 1).toBe(offset + 1);
    await expect(page.getByTestId("plan-week-label")).toHaveText(planWeekLabel(week!));
    const courseRows = plan.plan_items.filter((item) => item.plan_week_id === week!.id && item.program_inclusion_id === course!.id);
    expect(courseRows).toHaveLength(2);
    expect(courseRows.every((item) => item.count_per_week === 1 && item.occurrence_index !== null)).toBe(true);
    expect(new Set(courseRows.map((item) => item.occurrence_index)).size).toBe(2);
    await expect(page.getByTestId("plan-week-progress")).not.toContainText("0 из 0");
    await expect(page.getByText("На эту неделю пока ничего не запланировано.")).toHaveCount(0);
    await expect(rows).toHaveCount(2);
    await expect(page.getByText("Откроется")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^Начать: Подтягивания/ })).toHaveCount(2);
  };

  await assertCurrentWeekActionable();

  const nextWeek = page.getByRole("button", { name: "Следующая неделя" });
  const previousWeek = page.getByRole("button", { name: "Предыдущая неделя" });
  const futureOffsets = [1, 2, 3, 4];
  const visitFutureWeeks = async () => {
    for (const offset of futureOffsets) {
      await nextWeek.click();
      await assertFutureWeekHasCourse(offset);
    }
  };
  await visitFutureWeeks();

  // После reload недели всё ещё на месте (серверное состояние, не клиентская подмена).
  await page.reload();
  await nav(page, "Планы").click();
  await assertCurrentWeekActionable();
  await visitFutureWeeks();

  // Назад к текущей: старт по-прежнему доступен.
  for (const _ of futureOffsets) await previousWeek.click();
  await assertCurrentWeekActionable();
  expect(apiFailures).toEqual([]);
});
