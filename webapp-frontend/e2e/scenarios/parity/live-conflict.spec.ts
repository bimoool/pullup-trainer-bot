import { expect, test, type Page } from "@playwright/test";

import { noWakeLock } from "../../fixtures/builderFlow";
import { openAppAs, useLiveEngineV1 } from "../../fixtures/setup";
import { expectNoHorizontalOverflow, WIDTHS } from "../../fixtures/parity";
import type { TelegramTheme } from "../../fixtures/telegramMock";

// issue #306: сценарий экрана движка v1 (сессии engine_version = 1) — новые старты здесь на v1.
useLiveEngineV1(test);

// R-4 (#289): plan-путь старта тоже отвечает 409 active_session_exists, а пред-экран показывает тот же
// экран конфликта, что и workout-путь («Продолжить текущую»), а не сырую ошибку.
// Seeds (scripts/e2e_seed_all.sh): session_recovery 9985{01,11}(+retry) — «Тренировка восстановления».
const TITLE = "Тренировка восстановления";
const USERS: Record<number, { base: number; theme: TelegramTheme }> = {
  320: { base: 998_501, theme: "light" },
  390: { base: 998_511, theme: "dark" },
};

const appErrors = (errors: string[]) => noWakeLock(errors).filter((e) => !e.includes("Failed to load resource"));

async function initData(page: Page): Promise<string> {
  return page.evaluate(() => (window as unknown as { Telegram: { WebApp: { initData: string } } }).Telegram.WebApp.initData);
}

for (const width of WIDTHS) {
  const { base, theme } = USERS[width];
  test.describe(`Live conflict R-4 @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: width === 320 ? 640 : 844 } });
    test.setTimeout(90_000);

    test("старт из Планов при уже идущей тренировке: 409 → «Продолжить текущую», а не сырая ошибка", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, base + testInfo.retry, { theme, allowedApiStatuses: [409] });
      await page.getByTestId("my-workout-card").filter({ hasText: TITLE }).click();
      await page.getByRole("button", { name: "Добавить в план" }).click();
      await page.getByRole("button", { name: "Свободный пул" }).click();
      await page.getByRole("button", { name: "Добавить", exact: true }).click();
      const group = page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${TITLE}`) });
      await group.getByRole("button", { name: /^Начать: / }).click();
      const start = page.getByRole("button", { name: "Начать", exact: true });
      await expect(start).toBeVisible(); // SessionPreScreen

      // Параллельно (другое устройство) стартует другая тренировка.
      const headers = { "X-Telegram-Init-Data": await initData(page) };
      const workouts = (await (await page.request.get("/api/v2/workouts", { headers })).json()) as { workouts: { id: number; name?: string; title?: string }[] };
      const other = await page.request.post("/api/v2/sessions/live", {
        headers, data: { client_session_id: crypto.randomUUID(), workout_id: workouts.workouts[0].id },
      });
      expect(other.status()).toBe(200);
      const otherId = ((await other.json()) as { id: number }).id;

      const conflict = page.waitForResponse((r) => r.url().endsWith("/api/v2/sessions/live") && r.request().method() === "POST" && r.status() === 409);
      await start.click();
      expect((await (await conflict).json()).detail).toMatchObject({ code: "active_session_exists", active_session_id: otherId });

      const panel = page.getByTestId("active-session-conflict");
      await expect(panel).toBeVisible();
      await expect(panel).toContainText("Уже идёт другая тренировка");
      await expect(page.getByText(/Не удалось загрузить/)).toHaveCount(0);
      await expectNoHorizontalOverflow(page, "Конфликт активной сессии (plan-путь)");

      await panel.getByRole("button", { name: "Продолжить текущую" }).click();
      await expect(page.getByRole("heading", { name: "Приготовься", exact: true, level: 2 })).toBeVisible();

      expect(appErrors(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
