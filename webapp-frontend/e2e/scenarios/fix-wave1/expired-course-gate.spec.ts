import { execSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

import { clickAndSync, noWakeLock, playSets } from "../../fixtures/builderFlow";
import { openJournalEntry } from "../../fixtures/parity";
import { openAppAs, useLiveEngineV1 } from "../../fixtures/setup";

// issue #306: сценарий экрана движка v1 (сессии engine_version = 1) — новые старты здесь на v1.
useLiveEngineV1(test);

// Новый пользователь на каждый прогон (онбординг идёт через UI): id из секунд, либо GATE_TELEGRAM_ID.
const TG = Number(process.env.GATE_TELEGRAM_ID ?? 7_400_000 + (Math.floor(Date.now() / 1000) % 900_001));
const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");

function harness(args: string): string {
  return execSync(`python scripts/e2e_course_gate.py ${args}`, { cwd: REPO, env: { ...process.env, PYTHONPATH: REPO } }).toString();
}

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

test.setTimeout(150_000);
test.use({ actionTimeout: 10_000 });

const OWN_TITLE = "Моя свободная";

async function backToTabs(page: Page) {
  const tabbar = page.locator(".bottom-tabbar");
  await expect(tabbar.or(page.getByRole("button", { name: /Назад/ }).first()).first()).toBeVisible();
  if (!(await tabbar.isVisible())) {
    await page.getByRole("button", { name: /Назад/ }).first().click();
  }
}

async function createOwnWorkout(page: Page) {
  await backToTabs(page);
  await page.getByRole("button", { name: "Главная" }).click();
  await page.getByRole("button", { name: /^(Создать|Создать тренировку)$/ }).click();
  await page.getByRole("textbox").fill(OWN_TITLE);
  await page.getByRole("button", { name: "Создать и добавить упражнения" }).click();
  await page.getByRole("button", { name: "+ Добавить упражнение" }).click();
  await page.locator(".ux-pick").first().click();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  await expect(page.getByTestId("workout-item")).toHaveCount(1);
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByTestId("workout-detail-title")).toHaveText(OWN_TITLE);
}

async function openPlansAndStartCourse(page: Page) {
  await page.getByRole("button", { name: "Планы" }).click();
  await page.getByRole("button", { name: /^Начать: Подтягивания/ }).first().click();
}

test("Просроченный пользователь: курс за подпиской, свои тренировки доступны, grant возвращает курс", async ({ page }) => {
  page.on("dialog", (dialog) => void dialog.accept());
  const { consoleErrors, apiFailures } = await openAppAs(page, TG, { allowedApiStatuses: [402] });
  await onboard(page);

  // --- активный (trial) пользователь добавляет курс (UI) ---
  await page.getByRole("button", { name: /^Подтягивания/ }).first().click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await expect(page.getByRole("button", { name: "В плане" })).toBeVisible();
  await createOwnWorkout(page);

  // --- TEST HARNESS INJECTION: trial истёк (реальный пользователь доходит до этого ожиданием); кэш статуса остаётся `trial` ---
  harness(`expire ${TG}`);
  await page.reload();
  await expect(page.getByText("Что потренируем сегодня?")).toBeVisible();

  // --- курс: «Начать» ведёт на экран подписки, сессия не создаётся ---
  await openPlansAndStartCourse(page);
  const gate = page.getByTestId("subscription-required");
  await expect(gate).toBeVisible();
  await expect(gate).toContainText("подписк");
  await expect(page.getByText("Живая тренировка")).toHaveCount(0);

  // «Открыть подписку» -> экран подписки показывает «истекла» (статус не залип на «пробный период»)
  await gate.getByRole("button", { name: "Открыть подписку" }).click();
  await expect(page.getByText("истекла")).toBeVisible();

  // reload: гейт держится (сервер, а не состояние клиента)
  await page.reload();
  await openPlansAndStartCourse(page);
  await expect(page.getByTestId("subscription-required")).toBeVisible();
  await page.getByTestId("subscription-required").getByRole("button", { name: "Назад" }).click();

  // --- своя тренировка стартует без подписки ---
  await page.getByRole("button", { name: "Главная" }).click();
  await page.getByTestId("my-workout-card").filter({ hasText: OWN_TITLE }).click();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await page.getByRole("button", { name: "Начать", exact: true }).click(); // SessionPreScreen
  await expect(page.getByText("Живая тренировка")).toBeVisible();
  await playSets(page, ["8", "8", "8"]);
  await page.getByRole("button", { name: "Завершить", exact: true }).click();
  await clickAndSync(page, "Сохранить и завершить", "/complete");
  await expect(page.getByText("Тренировка завершена")).toBeVisible();
  await page.getByRole("button", { name: "Закрыть" }).click();

  // Свободная тренировка сегодня включила бы «ещё рано» (отдых между тренировками) для курса — убираем её из Журнала,
  // чтобы финальный старт курса проверял именно подписку (удаление свободной сессии прогрессию курса не трогает).
  await page.getByRole("button", { name: "Журнал" }).click();
  const entry = page.locator(".history-card").filter({ hasText: OWN_TITLE });
  await openJournalEntry(page, entry);
  await page.getByRole("button", { name: /Удалить/ }).click();
  await expect(page.locator(".history-card").filter({ hasText: OWN_TITLE })).toHaveCount(0);

  // --- TEST HARNESS: админ выдаёт 30 дней через реальный бот-хендлер admin_grant_days ---
  harness(`grant ${TG} 30`);
  await page.reload();
  await expect(page.getByText("Что потренируем сегодня?")).toBeVisible();

  // --- тот же план/курс на месте, «Начать» снова работает -> Live -> финиш ---
  await openPlansAndStartCourse(page);
  await expect(page.getByTestId("subscription-required")).toHaveCount(0);
  await page.getByRole("button", { name: "Начать", exact: true }).click(); // SessionPreScreen
  await expect(page.getByText("Живая тренировка")).toBeVisible();
  await page.getByRole("button", { name: "Завершить", exact: true }).click();
  await clickAndSync(page, "Сохранить и завершить", "/complete");
  await expect(page.getByText("Тренировка завершена")).toBeVisible();

  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});

test("Клиент считает доступ активным, сервер отвечает 402 — тот же экран подписки", async ({ page }) => {
  // подсказка has_access подменена на true (устаревшее состояние клиента); истина — 402 на старте
  await page.route("**/api/subscription", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), has_access: true } });
  });
  await openAppAs(page, TG + 1, { allowedApiStatuses: [402] });
  await onboard(page);
  await page.getByRole("button", { name: /^Подтягивания/ }).first().click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await expect(page.getByRole("button", { name: "В плане" })).toBeVisible();
  harness(`expire ${TG + 1}`); // TEST HARNESS INJECTION
  await page.reload();
  await expect(page.getByText("Что потренируем сегодня?")).toBeVisible();

  await openPlansAndStartCourse(page);
  const start = page.waitForResponse((r) => r.url().includes("/api/v2/sessions/live") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Начать", exact: true }).click(); // SessionPreScreen: подсказка «доступ есть»
  const response = await start;
  expect(response.status()).toBe(402);
  expect((await response.json()).detail.code).toBe("subscription_required");
  await expect(page.getByTestId("subscription-required")).toBeVisible();
  await expect(page.getByText("Живая тренировка")).toHaveCount(0);
});
