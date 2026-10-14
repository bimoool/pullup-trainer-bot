import { expect, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

/**
 * Аудит staging: на узком экране «Сохранить подход» (правка последнего подхода в отдыхе) был перекрыт липкой нижней
 * панелью Live. Пока открыта правка, панель скрыта (как у «Ещё подход»); правка сохраняется. Сид: live_engine 930622.
 */
test.use({ viewport: { width: 320, height: 568 }, isMobile: true, hasTouch: true });
test.setTimeout(90_000);

test("320×568: «Сохранить подход» не перекрыт нижней панелью и сохраняет правку", async ({ page }) => {
  const { apiFailures } = await openAppAs(page, 930_622);
  await page.getByRole("button", { name: "Планы" }).click();
  const group = page.locator(".plan-week-day-group").filter({ hasText: /^Движок: подходы/ });
  await group.getByRole("button", { name: /^Начать: / }).first().click();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл", { timeout: 10_000 });
  await page.getByLabel("Результат подхода").fill("7");
  await page.getByTestId("engine-submit").click();
  await expect(page.getByTestId("engine-edit-last")).toBeVisible({ timeout: 10_000 });

  await page.getByTestId("engine-edit-last").click();
  const save = page.getByRole("button", { name: "Сохранить подход" });
  // Как видит пользователь сразу после «Изменить» (без прокрутки), и после снятия фокуса с поля (десктопный Telegram Web).
  for (const focused of [true, false]) {
    if (!focused) {
      await page.getByLabel("Исправить подход").blur();
    }
    // Нижняя панель (если есть) не должна пересекаться с кнопкой — ни в фокусе поля, ни без него.
    const overlap = await save.evaluate((element) => {
      const box = element.getBoundingClientRect();
      return [...document.querySelectorAll(".live-transport")].some((panel) => {
        const p = panel.getBoundingClientRect();
        return p.top < box.bottom && p.bottom > box.top && p.left < box.right && p.right > box.left;
      });
    });
    expect(overlap, `«Сохранить подход» перекрыт нижней панелью (поле ${focused ? "в фокусе" : "без фокуса"})`).toBe(false);
  }
  await expect(page.locator(".live-transport")).toHaveCount(0); // панель скрыта на время правки
  await page.getByLabel("Исправить подход").fill("8");

  const posted = page.waitForResponse((r) => r.url().includes("/events") && r.request().method() === "POST" && r.ok());
  await save.click({ trial: false });
  const body = await (await posted).json();
  expect(body.engine.state.logs.find((log: { set_index: number; is_extra: boolean }) => log.set_index === 0 && !log.is_extra).value).toBe(8);
  await expect(page.getByTestId("log-panel-summary")).toContainText("8");
  await expect(page.locator(".live-transport")).toHaveCount(1); // правка закрыта — панель вернулась
  expect(apiFailures).toEqual([]);
});
