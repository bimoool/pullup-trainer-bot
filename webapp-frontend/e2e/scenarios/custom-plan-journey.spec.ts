import { expect, test } from "@playwright/test";

import { finishV2, noWakeLock, playSetsV2 } from "../fixtures/builderFlow";
import { openJournalEntry, openTab } from "../fixtures/parity";
import { openAppAs } from "../fixtures/setup";

const TELEGRAM_ID = 930_111;
const TITLE = "Золотая тренировка";

test("Свой план: объём 2/2/0/2, одно занятие зачтено, запись доступна для правки", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID + testInfo.retry);
  await openTab(page, "Планы");
  await page.getByTestId("plans-custom-plan").click();

  const form = page.getByTestId("custom-plan-screen");
  await form.getByLabel("Название плана").fill("План на четыре недели");
  await form.getByRole("checkbox", { name: TITLE, exact: true }).check();
  await form.getByTestId("custom-plan-weeks").fill("2 2 0 2");
  await expect(form.getByTestId("custom-plan-weeks-preview")).toHaveText("Н1: 2 · Н2: 2 · Н3: 0 · Н4: 2");
  await form.getByTestId("custom-plan-save").click();
  await expect(page.getByTestId("plans-custom-plan-row")).toContainText("План на четыре недели: Н1 2 · Н2 2 · Н3 0 · Н4 2");

  const progress = page.getByTestId("plan-week-progress");
  const week = page.getByTestId("plan-week-label");
  const rows = page.getByTestId("plans-row").filter({ hasText: TITLE });
  const nextWeek = page.getByRole("button", { name: "Следующая неделя" });
  const previousWeek = page.getByRole("button", { name: "Предыдущая неделя" });
  await expect(progress).toHaveText("Текущая неделя · 0 из 2");
  await expect(week).toHaveText(/^Неделя \d+ ·/);
  const currentWeek = Number((await week.textContent())?.match(/^Неделя (\d+) ·/)?.[1]);
  expect(currentWeek).toBeGreaterThan(0);
  await expect(rows).toHaveCount(2);
  for (const [offset, planned] of [[1, 2], [2, 0], [3, 2]]) {
    await nextWeek.click();
    await expect(week).toContainText(`Неделя ${currentWeek + offset} ·`);
    await expect(progress).toHaveText(`0 из ${planned}`);
    await expect(rows).toHaveCount(planned);
    if (planned === 0) {
      await expect(page.getByText("На эту неделю пока ничего не запланировано.")).toBeVisible();
    }
  }
  for (const offset of [2, 1, 0]) {
    await previousWeek.click();
    await expect(week).toContainText(`Неделя ${currentWeek + offset} ·`);
  }

  await rows.first().getByRole("button", { name: /^Начать: / }).click();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await playSetsV2(page, ["8", "7"]);
  await finishV2(page);
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();

  await openTab(page, "Планы");
  await expect(progress).toHaveText("Текущая неделя · 1 из 2");
  await expect(rows).toHaveCount(2);
  await expect(rows.and(page.locator('[data-done="true"]'))).toHaveCount(1);

  await openTab(page, "Журнал");
  const entry = page.getByTestId("journal-card").filter({ hasText: TITLE });
  await expect(entry).toHaveCount(1);
  await openJournalEntry(page, entry, "edit");
  const edit = page.getByTestId("journal-edit-form");
  await expect(edit.getByLabel("Подход 1: значение")).toHaveValue("8");
  await expect(edit.getByLabel("Подход 2: значение")).toHaveValue("7");
  await expect(edit.getByRole("button", { name: "Сохранить" })).toBeEnabled();
  await edit.getByRole("button", { name: "Отмена" }).click();

  expect(noWakeLock(consoleErrors)).toEqual([]);
  expect(apiFailures).toEqual([]);
});
