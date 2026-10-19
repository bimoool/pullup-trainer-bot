import { expect, test } from "@playwright/test";

import { collectConsoleErrors, collectUnexpectedApiFailures } from "../../fixtures/assertions";
import { runOwnerJourney } from "../../fixtures/ownerJourney";

// Тот же сквозной сценарий в браузерном режиме (вход test-login, шторки подтверждения в странице).
// Сиды: ux_editor_journey 941021 (desktop 1280) и 941022 (mobile 390).
test("браузер: остановить старый план → создать новый → расписание → перезагрузка", async ({ page }, info) => {
  const consoleErrors = collectConsoleErrors(page);
  const apiFailures = collectUnexpectedApiFailures(page, []);
  const login = await page.request.post("/api/web-auth/test-login", {
    data: { telegram_id: info.project.name === "web-mobile" ? 941_022 : 941_021 },
  });
  expect(login.status()).toBe(200);
  await page.goto("/");
  await runOwnerJourney(page);
  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});
