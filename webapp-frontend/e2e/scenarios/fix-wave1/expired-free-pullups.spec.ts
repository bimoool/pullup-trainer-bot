import { execSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test, type Page } from "@playwright/test";

import { finishV2, noWakeLock, playSetsV2 } from "../../fixtures/builderFlow";
import { buildInitData, getTestBotToken } from "../../fixtures/initData";
import { openAppAs } from "../../fixtures/setup";

/**
 * Правило владельца 2026-10-07 (app/domain/program_access.py): системная программа «Подтягивания» бесплатна
 * навсегда — пользователь с ИСТЁКШИМ trial добавляет её в план, стартует и завершает тренировку без подписки.
 * Гейт «курс за подпиской» проверяется отдельно на платном тестовом курсе (expired-course-gate.spec.ts).
 *
 * Пользователь создаётся онбордингом через UI; истечение — тот же харнесс, что в expired-course-gate
 * (scripts/e2e_course_gate.py expire): кэш статуса остаётся `trial`, срок — вчера.
 */

const TG = Number(process.env.FREE_TELEGRAM_ID ?? 7_600_000 + (Math.floor(Date.now() / 1000) % 900_001));
const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");

function harness(args: string): string {
  return execSync(`"${process.env.PYTHON ?? "python"}" scripts/e2e_course_gate.py ${args}`, {
    cwd: REPO, env: { ...process.env, PYTHONPATH: REPO },
  }).toString();
}

async function onboard(page: Page) {
  await page.getByLabel("Сколько подтягиваний вышло?").fill("8");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByRole("button", { name: "Да" }).click();
  await page.getByRole("button", { name: "Продолжить" }).click();
  await page.getByLabel("Твой вес в кг?").fill("78");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Рост в см?").fill("180");
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

test("Истёкший пользователь: бесплатные «Подтягивания» — в план, старт, завершение без подписки", async ({ page }) => {
  page.on("dialog", (dialog) => void dialog.accept());
  // Ни один ответ /api/* не должен быть 402: доступ к бесплатной программе не зависит от подписки.
  const { consoleErrors, apiFailures } = await openAppAs(page, TG);
  await onboard(page);

  await page.getByRole("button", { name: /^Подтягивания/ }).first().click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await expect(page.getByRole("button", { name: "В плане" })).toBeVisible();

  // TEST HARNESS INJECTION: trial истёк — подписка действительно не действует (сервер подтверждает).
  harness(`expire ${TG}`);
  const status = await page.request.get("/api/subscription", {
    headers: { "X-Telegram-Init-Data": buildInitData({ id: TG, firstName: "E2E" }, getTestBotToken()) },
  });
  expect((await status.json()).has_access).toBe(false);
  await page.reload();
  await expect(page.getByText("Что потренируем сегодня?")).toBeVisible();

  // Старт курса из Планов: никакого экрана подписки — пред-экран курса просит свои входы (V5.6).
  await page.getByRole("button", { name: "Планы" }).click();
  await page.getByRole("button", { name: /^Начать: Подтягивания/ }).first().click();
  await expect(page.getByTestId("subscription-required")).toHaveCount(0);
  await expect(page.getByTestId("course-setup-required")).toBeVisible();
  await page.getByTestId("course-input-volume_capacity").fill("10");
  await page.getByTestId("course-volume-band-name").fill("Синяя");
  await page.getByTestId("course-volume-band-colour").fill("синяя");
  await page.getByTestId("course-volume-band-attachment").fill("петля на перекладине");
  await page.getByTestId("course-volume-band-position").fill("стопа");
  await page.getByTestId("course-strength-band-bodyweight").check();
  await page.getByTestId("course-setup-save").click();
  await expect(page.getByText("Блок 1: 7/7/7/7+")).toBeVisible();

  // Старт и завершение — на сервере, без 402.
  const started = page.waitForResponse((r) => r.url().includes("/api/v2/sessions/live") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  expect((await started).status()).toBe(200);
  await expect(page.getByText("Живая тренировка")).toBeVisible();
  await expect(page.getByTestId("subscription-required")).toHaveCount(0);
  await playSetsV2(page, ["10", "10", "10"]);
  await finishV2(page, { early: true });
  await expect(page.getByText("Тренировка завершена").first()).toBeVisible();
  await page.getByRole("button", { name: "Закрыть" }).click();

  // Журнал: сохранённая сессия видна и переживает reload — подписка для этого не нужна.
  await page.reload();
  await page.getByRole("button", { name: "Журнал", exact: true }).click();
  await expect(page.locator(".history-card").filter({ hasText: "Подтягивания" }).first()).toBeVisible();

  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});
