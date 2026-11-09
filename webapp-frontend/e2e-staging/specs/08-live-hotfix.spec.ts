import type { Page } from "@playwright/test";
import { expect, test } from "../fixtures/app";

async function start(page: Page) {
  await expect(page.locator(".bottom-tabbar")).toBeVisible();
  await page.getByRole("button", { name: "Планы", exact: true }).click();
  await page.getByRole("button", { name: /^Начать: Подтягивания/ }).first().click();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await expect(page.getByTestId("engine-load")).toHaveText("Свой вес");
}

async function submit(page: Page, value: string, expectedSet?: string) {
  await expect(page.getByTestId("engine-saving")).toHaveCount(0);
  if (await page.getByTestId("engine-skip").count()) await page.getByTestId("engine-skip").click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл");
  if (expectedSet) await expect(page.getByTestId("engine-target")).toContainText(expectedSet);
  await page.getByRole("textbox", { name: "Результат подхода" }).fill(value);
  await page.getByTestId("engine-submit").click();
  await expect(page.getByTestId("engine-saving")).toHaveCount(0);
}

test("R-HOTFIX full 10x5: nine minute rests, then strength +10 kg and one journal entry", async ({ qa }) => {
  const session = await qa("qa_hotfix_full");
  const { page } = session;
  await start(page);
  for (let index = 0; index < 10; index++) {
    await submit(page, "5", `Подход ${index + 1}/10`);
    await expect(page.getByTestId("engine-phase")).toHaveText("Отдых");
    await expect(page.getByTestId("engine-timer")).toHaveText(index < 9 ? /^(0:5[0-9]|1:00)$/ : /^1[45]:[0-5][0-9]$/);
    await expect(page.getByTestId("engine-next-block")).toHaveCount(index < 9 ? 0 : 1);
  }
  await page.getByTestId("engine-skip").click();
  await expect(page.getByTestId("engine-load")).toHaveText("+10 кг");
  for (let index = 0; index < 5; index++) await submit(page, "3", `Подход ${index + 1}/5`);
  await expect(page.getByTestId("engine-confirm")).toBeVisible();
  for (const group of await page.locator('[data-testid^="check-technique-"], [data-testid^="check-rest-"]').all()) {
    await group.getByRole("button", { name: "Да", exact: true }).click();
  }
  await page.getByTestId("engine-confirm-submit").click();
  await expect(page.getByTestId("engine-complete")).toBeVisible();
  await page.getByTestId("engine-save").click();
  await expect(page.getByTestId("course-progression")).toBeVisible();
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  await page.reload();
  await expect(page.locator(".bottom-tabbar")).toBeVisible();
  await page.getByRole("button", { name: "Журнал", exact: true }).click();
  await expect(page.locator(".history-card").filter({ hasText: "Подтягивания" })).toHaveCount(1);
  session.assertClean();
});

test("R-HOTFIX technique-stop requires explicit confirmation and explains block end", async ({ qa }) => {
  const session = await qa("qa_hotfix_technique");
  const { page } = session;
  await start(page);
  for (let index = 0; index < 3; index++) await submit(page, "5");
  await page.getByTestId("engine-skip").click();
  await expect(page.getByTestId("engine-target")).toContainText("Подход 4/10");
  // Native Telegram popup transport is replaced by a browser dialog; API and engine stay real.
  await page.evaluate(() => {
    const w = window as typeof window & { Telegram?: { WebApp?: { showConfirm?: (s: string, cb: (v: boolean) => void) => void } } };
    if (w.Telegram?.WebApp) w.Telegram.WebApp.showConfirm = (s, cb) => cb(window.confirm(s));
  });
  page.once("dialog", dialog => dialog.dismiss());
  await page.getByTestId("engine-submit-technique-broken").click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл");
  await expect(page.getByTestId("engine-target")).toContainText("Подход 4/10");
  page.once("dialog", dialog => dialog.accept());
  await page.getByTestId("engine-submit-technique-broken").click();
  await expect(page.getByTestId("engine-next-block")).toBeVisible();
  await expect(page.getByTestId("engine-rest-context")).toContainText("отмечено нарушение техники");
  session.assertClean();
});

test("R-HOTFIX finish early: back preserves session, confirmation saves it once", async ({ qa }) => {
  const session = await qa("qa_hotfix_finish");
  const { page } = session;
  await start(page);
  await submit(page, "5");
  await page.getByTestId("engine-finish").click();
  await expect(page.getByTestId("engine-finish-confirm")).toBeVisible();
  await page.getByRole("button", { name: "Назад", exact: true }).click();
  await expect(page.getByTestId("engine-finish-confirm")).toHaveCount(0);
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых");
  await page.getByTestId("engine-finish").click();
  await page.getByTestId("engine-finish-confirm").click();
  await expect(page.getByText("Прогрессия не пересчитана — сессия завершена досрочно.")).toBeVisible();
  session.assertClean();
});
