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
import { openAppAs, useLiveEngineV1 } from "../../fixtures/setup";

// issue #306: сценарий экрана движка v1 (сессии engine_version = 1) — новые старты здесь на v1.
useLiveEngineV1(test);

const TELEGRAM_ID = 7_900_000 + (Date.now() % 90_000);
const BASE_URL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:8001";

const nav = (page: Page, name: string) => page.getByRole("button", { name, exact: true });

async function onboard(page: Page) {
  await page.getByLabel("Число подтягиваний").fill("8");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByRole("button", { name: "Да" }).click();
  await page.getByRole("button", { name: "Продолжить" }).click();
  await page.getByLabel("Вес, кг").fill("78");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Рост, см").fill("180");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Пол").selectOption({ label: "Мужской" });
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Дата рождения").fill("1992-04-15");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Часовой пояс").selectOption({ label: "Москва (UTC+3)" });
  await page.getByRole("button", { name: "Готово" }).click();
  await expect(page.getByText("Что потренируем сегодня?")).toBeVisible();
}

// issue #304 (AD-4, §6, J12): неделя курса — 3 занятия (одна строка = одно занятие), будущие недели видимы И
// стартуемы (замок «Откроется <дата>» снят).
test("«Подтягивания»: недели 2 и 3 не пустые — 3 занятия, будущие стартуемы", async ({ page }) => {
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

  const rows = page.getByTestId("plans-row").filter({ hasText: "Подтягивания" });
  const assertCurrentWeekActionable = async () => {
    await expect(page.getByTestId("plan-week-progress")).toContainText("Текущая неделя");
    await expect(page.getByTestId("plan-week-progress")).not.toContainText("0 из 0");
    await expect(rows).toHaveCount(3);
    await expect(page.getByRole("button", { name: /^Начать: Подтягивания/ }).first()).toBeVisible();
  };
  // Будущая неделя: занятия курса на месте, не пустое состояние, и их можно начать (§6).
  const assertFutureWeekHasCourse = async (weekNumber: number) => {
    await expect(page.getByTestId("plan-week-label")).toContainText(`Неделя ${weekNumber}`);
    await expect(page.getByTestId("plan-week-progress")).not.toContainText("0 из 0");
    await expect(page.getByText("На эту неделю пока ничего не запланировано.")).toHaveCount(0);
    await expect(rows).toHaveCount(3);
    await expect(page.getByText("Откроется")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^Начать: Подтягивания/ })).toHaveCount(3);
  };

  await assertCurrentWeekActionable();

  await page.getByRole("button", { name: "Следующая неделя" }).click();
  await assertFutureWeekHasCourse(2);
  await page.getByRole("button", { name: "Следующая неделя" }).click();
  await assertFutureWeekHasCourse(3);

  // После reload недели всё ещё на месте (серверное состояние, не клиентская подмена).
  await page.reload();
  await nav(page, "Планы").click();
  await assertCurrentWeekActionable();
  await page.getByRole("button", { name: "Следующая неделя" }).click();
  await assertFutureWeekHasCourse(2);
  await page.getByRole("button", { name: "Следующая неделя" }).click();
  await assertFutureWeekHasCourse(3);

  // Назад к текущей: ‹ ‹ — старт по-прежнему доступен.
  await page.getByRole("button", { name: "Предыдущая неделя" }).click();
  await page.getByRole("button", { name: "Предыдущая неделя" }).click();
  await assertCurrentWeekActionable();
  expect(apiFailures).toEqual([]);
});
