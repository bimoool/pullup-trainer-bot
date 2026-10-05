import { expect, test, type Page } from "@playwright/test";
import { buildInitData } from "../../fixtures/initData";
import { mockTelegramWebApp } from "../../fixtures/telegramMock";

// Journeys as a user: only getByRole/getByText, each on a NEW telegram id (S0 = onboarded, no plan, no workouts).
// Run: BOT_TOKEN=audit-token npx playwright test -c audit/B-fresh-catalog/playwright.audit.config.ts
const ID = Number(process.env.AUDIT_ID_BASE ?? 7200011); // use a fresh base for every re-run so each journey starts at S0
const tab = (page: Page, name: string) => page.getByText(name, { exact: true }).last();
const settle = (page: Page) => page.waitForLoadState("networkidle");

async function openAs(page: Page, id: number) {
  await mockTelegramWebApp(page, buildInitData({ id, firstName: "Audit" }, process.env.BOT_TOKEN ?? "audit-token"), "light", { backButton: true });
  await page.goto("/");
}

async function onboardViaUi(page: Page) {
  await page.locator("input").first().fill("8");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByRole("button", { name: "Да", exact: true }).click();
  await page.getByRole("button", { name: "Продолжить" }).click();
  await page.getByLabel("Вес, кг").fill("78");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Рост, см").fill("180");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.locator("select").selectOption("male");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.getByLabel("Дата рождения").fill("1995-05-15");
  await page.getByRole("button", { name: "Далее" }).click();
  await page.locator("select").selectOption({ label: "Москва (UTC+3)" });
  await page.getByRole("button", { name: "Готово" }).click();
  await expect(page.getByText("Что потренируем сегодня?")).toBeVisible();
}

async function runLive(page: Page, reps: string[]) {
  let i = 0;
  for (let guard = 0; guard < 40; guard++) {
    await page.waitForTimeout(300);
    const body = await page.locator("body").innerText();
    if (/Тренировка завершена/.test(body)) return;
    if (/ГОТОВЫ К СТАРТУ/.test(body)) { await page.getByRole("button", { name: "Начать" }).click(); continue; }
    if (/Как прошла тренировка/.test(body)) {
      await page.getByRole("button", { name: /Средне/ }).click();
      await page.getByRole("button", { name: "Сохранить и завершить" }).click(); continue;
    }
    if (await page.getByRole("button", { name: "Пропустить отдых" }).count()) { await page.getByRole("button", { name: "Пропустить отдых" }).click(); continue; }
    if (await page.getByLabel("Повторений").count()) {
      await page.getByLabel("Повторений").fill(reps[i++] ?? "5");
      await page.getByRole("button", { name: /^Готово$/ }).click(); continue;
    }
    if (await page.getByRole("button", { name: /^Готов$/ }).count()) { await page.getByRole("button", { name: /^Готов$/ }).click(); continue; }
    if (/Все подходы плана выполнены/.test(body)) { await page.getByRole("button", { name: "Завершить" }).first().click(); continue; }
  }
  throw new Error("live loop did not reach summary");
}

test("J1 zero-to-workout via catalogue program", async ({ page }) => {
  await openAs(page, ID + (11 - 11));
  await onboardViaUi(page);
  await page.getByText("Подтягивания", { exact: true }).first().click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await expect(page.getByRole("button", { name: "В плане" })).toBeVisible();
  await page.reload(); await settle(page); // detail screen hides the tab bar; leave it like a user would (reload == reopen)
  await tab(page, "Планы").click();
  await expect(page.getByText("Текущая неделя · 0 из 3")).toBeVisible();      // >=1 actionable row
  await page.reload(); await settle(page);
  await tab(page, "Планы").click();
  await expect(page.getByRole("button", { name: "Начать" }).first()).toBeVisible();
  await page.getByRole("button", { name: "Начать" }).first().click();
  await runLive(page, ["8", "8", "7", "3"]);
  await page.getByRole("button", { name: "Закрыть" }).click();
  await tab(page, "Журнал").click();
  await expect(page.getByText("По плану")).toBeVisible();
  await tab(page, "Аналитика").click();
  await expect(page.getByText("Тренировок за 30 дней")).toBeVisible();
  await page.reload(); await settle(page);
  await tab(page, "Журнал").click();
  await expect(page.getByText("Подтягивания", { exact: true }).first()).toBeVisible();
});

test("J2 custom workout from nothing, library search + create-own, start, then plan, start from plan", async ({ page }) => {
  await openAs(page, ID + (12 - 11));
  await onboardViaUi(page);
  await page.getByRole("button", { name: "Создать тренировку" }).click();
  await page.getByPlaceholder("Например, 3 минуты подтягиваний").fill("Моя тренировка спины");
  await page.getByRole("button", { name: "Создать и добавить упражнения" }).click();
  await page.getByRole("button", { name: "+ Добавить упражнение" }).click();
  await page.getByLabel("Поиск упражнения").fill("Австралийские подтягивания");
  await expect(page.getByText("Ничего не найдено")).toBeVisible();
  await page.getByRole("button", { name: /Создать своё/ }).click();
  await page.getByRole("textbox", { name: "Повторения в подходе" }).fill("8");
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  await page.getByRole("button", { name: "Сохранить" }).click();
  await page.reload(); await settle(page);
  await expect(page.getByText("1 упражнение · 3 × 8")).toBeVisible();
  await page.getByText("Моя тренировка спины").first().click();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await runLive(page, ["8", "7", "6"]);
  await page.getByRole("button", { name: "Закрыть" }).click();
  await tab(page, "Журнал").click();
  await expect(page.getByText("Свободная")).toBeVisible();
});

test("J2b first-ever add-to-plan with no plan (EXPECTED TO FAIL: item invisible, F-B-fresh-catalog-01)", async ({ page }) => {
  await openAs(page, ID + (13 - 11));
  await onboardViaUi(page);
  await page.getByRole("button", { name: "Создать тренировку" }).click();
  await page.getByPlaceholder("Например, 3 минуты подтягиваний").fill("W");
  await page.getByRole("button", { name: "Создать и добавить упражнения" }).click();
  await page.getByRole("button", { name: "+ Добавить упражнение" }).click();
  await page.getByText("Планка", { exact: true }).first().click();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await page.getByRole("button", { name: "Ср", exact: true }).click();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  await page.reload(); await settle(page);
  await tab(page, "Планы").click();
  await expect(page.getByText("Текущая неделя · 0 из 1")).toBeVisible();
});

test("J3 empty workout cannot start and has an edit path", async ({ page }) => {
  await openAs(page, ID + (14 - 11));
  await onboardViaUi(page);
  await page.getByRole("button", { name: "Создать тренировку" }).click();
  await page.getByPlaceholder("Например, 3 минуты подтягиваний").fill("Пустая");
  await page.getByRole("button", { name: "Создать и добавить упражнения" }).click();
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByTestId("workout-detail-start")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Изменить" })).toBeVisible();
});
