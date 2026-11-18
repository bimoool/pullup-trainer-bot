import { expect, test, type Page } from "@playwright/test";

import { finishV2, noWakeLock, playSetsV2 } from "../fixtures/builderFlow";
import { openJournalEntry, openTab } from "../fixtures/parity";
import { openAppAs } from "../fixtures/setup";

const TELEGRAM_ID = 930_121;
const TITLE = "Золотая тренировка";

async function completeFromPrescreen(page: Page) {
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await playSetsV2(page, ["8", "7"]);
  await finishV2(page);
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
}

test("Прямой старт и копия записи не засчитывают занятие плана", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID + testInfo.retry);
  const workout = page.getByTestId("my-workout-card").filter({ hasText: TITLE });
  await workout.click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await page.getByRole("button", { name: "Свободный пул" }).click();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();

  const progress = page.getByTestId("plan-week-progress");
  const row = page.getByTestId("plans-row").filter({ hasText: TITLE });
  await expect(row).toHaveCount(1);
  await expect(progress).toHaveText("Текущая неделя · 0 из 1");

  // Start the same workout from its own detail while the plan occurrence is open.
  await openTab(page, "Главная");
  await workout.click();
  await page.getByTestId("workout-detail-start").click();
  await completeFromPrescreen(page);

  const entries = page.getByTestId("journal-card").filter({ hasText: TITLE });
  await openTab(page, "Журнал");
  await expect(entries).toHaveCount(1);
  await expect(entries.getByTestId("journal-kind-badge")).toHaveText("Свободная");
  await openTab(page, "Планы");
  await expect(progress).toHaveText("Текущая неделя · 0 из 1");
  await expect(row).toHaveAttribute("data-done", "false");

  // Start via the occurrence as a positive control, then clone its Journal entry.
  await row.getByRole("button", { name: /^Начать: / }).click();
  await completeFromPrescreen(page);
  await openTab(page, "Планы");
  await expect(progress).toHaveText("Текущая неделя · 1 из 1");
  await expect(row).toHaveAttribute("data-done", "true");

  await openTab(page, "Журнал");
  await expect(entries).toHaveCount(2);
  const planned = entries.filter({
    has: page.getByTestId("journal-kind-badge").filter({ hasText: /^По плану$/ }),
  });
  await openJournalEntry(page, planned, "clone");
  const cloneForm = page.getByTestId("journal-clone-form");
  const cloned = page.waitForResponse((response) =>
    response.request().method() === "POST" && /\/api\/v2\/sessions\/\d+\/clone$/.test(new URL(response.url()).pathname),
  );
  await cloneForm.getByRole("button", { name: "Создать копию", exact: true }).click();
  const response = await cloned;
  expect(response.status()).toBe(201);
  // The weekly count could saturate at 1/1 even if the copy inherited the link.
  expect((await response.json()).plan_item_id).toBeNull();
  await expect(cloneForm).toHaveCount(0);
  await expect(entries).toHaveCount(3);
  await expect(planned).toHaveCount(1);
  await expect(entries.getByTestId("journal-kind-badge").filter({ hasText: /^Записана задним числом$/ })).toBeVisible();
  await openTab(page, "Планы");
  await expect(progress).toHaveText("Текущая неделя · 1 из 1");
  await expect(row).toHaveCount(1);
  await expect(row).toHaveAttribute("data-done", "true");

  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});
