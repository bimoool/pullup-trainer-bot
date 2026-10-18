import { expect, test } from "@playwright/test";

import { openAppAs } from "../../fixtures/setup";
import { authUserId } from "../../fixtures/webAuth";

// Mini App не затронут браузерным входом: внутри Telegram initData главнее любой cookie, экран входа не появляется.
test("внутри Telegram initData главнее: экран входа не показывается, /api/web-auth/session не вызывается", async ({ page, context }, testInfo) => {
  const id = authUserId(testInfo, 8);
  const sessionCalls: string[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/api/web-auth/")) {
      sessionCalls.push(req.url());
    }
  });
  // Посторонняя «просроченная» cookie не должна ни мешать, ни подменять пользователя.
  await context.addCookies([{ name: "pullup_web_session", value: "stale-token", url: testInfo.project.use.baseURL ?? "http://127.0.0.1:8081" }]);

  const { consoleErrors, apiFailures } = await openAppAs(page, id);

  await expect(page.getByTestId("login-screen")).toHaveCount(0);
  await expect(page.locator(".plan-title")).toHaveText("Главная");
  await expect(page.getByTestId("my-workout-card")).toHaveCount(2);
  expect(sessionCalls).toEqual([]);
  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});
