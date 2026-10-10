import { expect, test, type Page } from "@playwright/test";

import { noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs, useLiveEngineV1 } from "../../fixtures/setup";
import type { TelegramTheme } from "../../fixtures/telegramMock";

// issue #306: сценарий экрана движка v1 (сессии engine_version = 1) — новые старты здесь на v1.
useLiveEngineV1(test);

// R-4 follow-up (#293 N2/N3). Seeds (scripts/e2e_seed_all.sh): session_recovery 99360x/99361x (N2), 99362x/99363x (N3);
// все мутируют; id + retry.
const USERS: Record<number, { finish: number; offline: number; theme: TelegramTheme }> = {
  320: { finish: 993_601, offline: 993_621, theme: "light" },
  390: { finish: 993_611, offline: 993_631, theme: "dark" },
};
const TITLE = "Тренировка восстановления";

const appErrors = (errors: string[]) => noWakeLock(errors).filter((e) => !e.includes("Failed to load resource"));

async function addToPlanAndOpenPre(page: Page) {
  await page.getByTestId("my-workout-card").filter({ hasText: TITLE }).click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await page.getByRole("button", { name: "Свободный пул" }).click();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  const group = page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${TITLE}`) });
  await group.getByRole("button", { name: /^Начать: / }).click();
  await expect(page.getByTestId("session-pre")).toBeVisible();
  return group;
}

for (const width of WIDTHS) {
  const { finish, offline, theme } = USERS[width as 320 | 390];
  test.describe(`R-4 follow-up @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: width === 320 ? 640 : 844 } });
    test.setTimeout(150_000);

    test("N2: досылка завершения дольше 5 с — «Завершение отправляется…» с повтором, а не «Продолжить текущую»", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, finish + testInfo.retry, { theme, allowedApiStatuses: [500, 409] });
      const started = page.waitForResponse((r) => r.url().endsWith("/api/v2/sessions/live") && r.request().method() === "POST");
      await addToPlanAndOpenPre(page);
      await page.getByRole("button", { name: "Начать", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Приготовься", exact: true, level: 2 })).toBeVisible();
      const firstId = ((await (await started).json()) as { id: number }).id;

      // Завершение падает (500) → «Выйти»: в очереди, на сервере ещё STARTED.
      let mode: "fail" | "hold" | "pass" = "fail";
      let release: () => void = () => {};
      const gate = new Promise<void>((resolve) => { release = resolve; });
      await page.route("**/api/v2/sessions/live/*/complete", async (route) => {
        if (mode === "fail") {
          await route.fulfill({ status: 500, body: "boom" });
        } else {
          if (mode === "hold") {
            await gate;
          }
          await route.continue();
        }
      });
      await page.getByRole("button", { name: "Завершить", exact: true }).click();
      await page.getByTestId("workout-review").getByRole("button", { name: "Сохранить и завершить" }).click();
      await expect(page.getByTestId("finish-pending")).toHaveAttribute("data-state", "retry");
      await page.getByTestId("finish-leave").click();
      mode = "hold"; // досылка зависает дольше потолка ожидания (5 с)

      await openTab(page, "Главная");
      await page.getByTestId("my-workout-card").filter({ hasText: TITLE }).click();
      await page.getByTestId("workout-detail-start").click();

      // Потолок 5 с истёк, а сервер ещё видит ту самую сессию активной → «отправляется», не «Продолжить».
      const pending = page.getByTestId("finish-pending");
      await expect(pending).toBeVisible({ timeout: 20_000 });
      await expect(pending).toContainText("Завершение прошлой тренировки");
      await expect(pending).toContainText("отправляется");
      await expect(page.getByTestId("active-session-conflict")).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Продолжить текущую" })).toHaveCount(0);
      for (const name of ["Повторить", "Назад"]) {
        const box = await pending.getByRole("button", { name, exact: true }).boundingBox();
        expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
      }
      await expectNoHorizontalOverflow(page, "Завершение отправляется");

      // Досылка дошла → «Повторить» заново досылает и сразу стартует новую тренировку.
      mode = "pass";
      release();
      await pending.getByRole("button", { name: "Повторить", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Приготовься", exact: true, level: 2 })).toBeVisible();
      const active = await page.evaluate(async () => {
        const initData = (window as unknown as { Telegram: { WebApp: { initData: string } } }).Telegram.WebApp.initData;
        const r = await fetch("/api/v2/sessions/live/active", { headers: { "X-Telegram-Init-Data": initData } });
        return (await r.json()) as { id: number } | null;
      });
      expect(active?.id).not.toBe(firstId);

      expect(appErrors(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("N3: ошибка на пред-экране (офлайн «Начать») — «Повторить» и «Назад» ≥44px", async ({ page, context }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, offline + testInfo.retry, { theme, backButton: true });
      const group = await addToPlanAndOpenPre(page);

      await context.setOffline(true);
      await page.getByRole("button", { name: "Начать", exact: true }).click();
      const retry = page.getByRole("button", { name: "Повторить", exact: true });
      const back = page.getByRole("button", { name: "Назад", exact: true });
      await expect(page.getByText(/Не удалось загрузить/)).toBeVisible();
      await expect(retry).toBeVisible();
      await expect(back).toBeVisible();
      for (const button of [retry, back]) {
        expect((await button.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44);
      }
      await expectNoHorizontalOverflow(page, "Ошибка пред-экрана");

      // «Назад» — тот же выход, что у Telegram BackButton: обратно в Планы.
      await context.setOffline(false); // «Планы» перезагружаются при возврате
      await back.click();
      await expect(page.getByTestId("session-pre")).toHaveCount(0);
      await expect(group.getByRole("button", { name: /^Начать: / })).toBeVisible();

      // Снова офлайн → ошибка → сеть вернулась → «Повторить» стартует тренировку.
      await group.getByRole("button", { name: /^Начать: / }).click();
      await expect(page.getByTestId("session-pre")).toBeVisible();
      await context.setOffline(true);
      await page.getByRole("button", { name: "Начать", exact: true }).click();
      await expect(retry).toBeVisible();
      await context.setOffline(false);
      await retry.click();
      await expect(page.getByRole("heading", { name: "Приготовься", exact: true, level: 2 })).toBeVisible();

      expect(appErrors(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
