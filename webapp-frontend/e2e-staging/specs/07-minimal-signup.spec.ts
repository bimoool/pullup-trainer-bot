import { expect, test } from "@playwright/test";

import { buildInitData, launchUrl, QA_IDENTITIES, stagingBotToken } from "../fixtures/initData";

test("R-V2 minimal signup: optional demographics, no body fields, profile survives reload", async ({ page, baseURL }) => {
  const telegramId = QA_IDENTITIES.qa_signup;
  const initData = buildInitData(telegramId, stagingBotToken());
  await page.goto(launchUrl(baseURL!, initData));
  await page.getByLabel("Сколько подтягиваний вышло?").fill("8");
  await page.getByRole("button", { name: "Далее", exact: true }).click();
  await page.getByRole("button", { name: "Да", exact: true }).click();
  await page.getByRole("button", { name: "Продолжить", exact: true }).click();
  await expect(page.getByLabel("Твой вес в кг?")).toHaveCount(0);
  await expect(page.getByLabel("Рост в см?")).toHaveCount(0);
  await expect(page.getByLabel("Пол?")).toHaveValue("");
  await page.getByRole("button", { name: "Далее", exact: true }).click();
  await expect(page.getByLabel("Дата рождения?")).toHaveValue("");
  await page.getByRole("button", { name: "Далее", exact: true }).click();
  await page.getByLabel("Часовой пояс?").selectOption("Asia/Yekaterinburg");
  const submitted = page.waitForRequest((r) => r.url().endsWith("/api/onboarding/questionnaire") && r.method() === "POST");
  await page.getByRole("button", { name: "Готово", exact: true }).click();
  expect((await submitted).postDataJSON()).toEqual({ timezone: "Asia/Yekaterinburg" });
  await expect(page.locator(".bottom-tabbar")).toBeVisible();
  await page.reload();
  await expect(page.locator(".bottom-tabbar")).toBeVisible();
  const response = await page.request.get("/api/profile", {
    headers: { "X-Telegram-Init-Data": initData },
  });
  expect(response.ok()).toBe(true);
  expect(await response.json()).toMatchObject({
    weight_kg: null, height_cm: null, gender: null, birth_date: null, timezone: "Asia/Yekaterinburg",
  });
});
