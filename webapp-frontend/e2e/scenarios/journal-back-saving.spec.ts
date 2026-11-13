import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";
import { pressTelegramBackButton } from "../fixtures/telegramMock";

// journal_edit fixtures: separate users for each case and retry.
for (const [index, mode] of (["edit", "clone"] as const).entries()) {
  for (const failure of [false, true]) {
    test(`${mode}: Telegram Back preserves the saving form until a real ${failure ? "422" : "success"} response`, async ({ page }, testInfo) => {
      const telegramId = 939_961 + index * 4 + Number(failure) * 2 + testInfo.retry;
      await openAppAs(page, telegramId, { backButton: true, allowedApiStatuses: [422] });
      await page.getByRole("button", { name: "Журнал", exact: true }).click();
      await page.locator(".history-card-clickable").filter({ hasText: "Моя силовая" }).first().click();
      await page.getByTestId(`journal-sheet-${mode}`).click();
      const form = page.getByTestId(`journal-${mode}-form`);
      await expect(form).toBeVisible();
      if (mode === "edit") {
        await page.getByLabel("Комментарий к тренировке").fill("Draft kept during saving");
      }
      const date = page.getByLabel(mode === "edit" ? "Дата тренировки" : "Дата новой записи");
      const draftDate = await date.inputValue();
      let release = () => {};
      const gate = new Promise<void>((resolve) => { release = resolve; });
      let received = (status: number) => { void status; };
      const responseReceived = new Promise<number>((resolve) => { received = resolve; });
      await page.route("**/api/v2/sessions/**", async (route) => {
        if (route.request().method() !== (mode === "edit" ? "PATCH" : "POST")) {
          await route.continue();
          return;
        }
        // Real API and Postgres; only hold delivery of the resulting response.
        // A future date exercises the API's real validation failure.
        const response = await route.fetch(failure ? {
          postData: { ...route.request().postDataJSON(), performed_on: "2999-01-01" },
        } : {});
        received(response.status());
        await gate;
        await route.fulfill({ response });
      });
      try {
        await form.getByRole("button", { name: mode === "edit" ? "Сохранить" : "Создать копию", exact: true }).click();
        expect(await responseReceived).toBe(failure ? 422 : mode === "edit" ? 200 : 201);
        await expect(form.getByRole("button", { name: "Отмена", exact: true })).toBeDisabled();
        await page.getByTestId(`journal-${mode}-back`).click();
        await expect(form).toBeVisible();
        await pressTelegramBackButton(page);
        await expect(form).toBeVisible();
        await expect(date).toHaveValue(draftDate);
      } finally {
        release();
      }
      if (failure) {
        await expect(form.getByRole("alert")).toBeVisible();
        await expect(date).toHaveValue(draftDate);
        if (mode === "edit") {
          await expect(page.getByLabel("Комментарий к тренировке")).toHaveValue("Draft kept during saving");
        }
        await expect(form.getByRole("button", { name: "Отмена", exact: true })).toBeEnabled();
        await pressTelegramBackButton(page);
        await expect(form).toHaveCount(0);
      } else {
        await expect(form).toHaveCount(0);
      }
      await expect(page.locator(".history-card-clickable").first()).toBeVisible();
    });
  }
}
