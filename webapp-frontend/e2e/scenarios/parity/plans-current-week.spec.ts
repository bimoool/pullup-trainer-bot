import { expect, test } from "@playwright/test";

import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";

// #283 (review fix) — «Добавить в план» кладёт строку в ТЕКУЩУЮ неделю, даже если после #275 в плане
// уже есть будущие недели (раньше AddToPlanScreen брал последнюю неделю списка = самую дальнюю).
// Seed: scripts/e2e_seed.py golden_journey — своя Workout «Золотая тренировка», пустая текущая неделя.
// Мутирующий сценарий: по пользователю на ширину/тему и на retry (id + retry).
const USERS = { 320: { id: 990_401, theme: "light" }, 390: { id: 990_411, theme: "dark" } } as const;

for (const width of WIDTHS) {
  const { id, theme } = USERS[width as 320 | 390];

  test.describe(`Plans current week @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 800 } });
    test.setTimeout(90_000);

    test("«Добавить в план» из Workout Detail попадает в текущую неделю, а не в будущую", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, id + testInfo.retry, { theme });
      await openTab(page, "Планы");

      const label = page.getByTestId("plan-week-label");
      const counters = page.getByTestId("plan-item-counter");
      const next = page.getByRole("button", { name: "Следующая неделя" });
      const prev = page.getByRole("button", { name: "Предыдущая неделя" });

      const currentLabel = (await label.textContent()) ?? "";
      await expect(counters).toHaveCount(0);

      // › за текущей неделей создаёт будущую (последняя неделя списка теперь — будущая).
      await next.click();
      await expect(label).not.toHaveText(currentLabel);
      await prev.click();
      await expect(label).toHaveText(currentLabel);

      // Workout Detail → «Добавить в план» → день → «Добавить».
      await openTab(page, "Главная");
      await page.getByTestId("my-workout-card").filter({ hasText: "Золотая тренировка" }).click();
      await expect(page.getByTestId("workout-detail")).toBeVisible();
      await page.getByRole("button", { name: "Добавить в план" }).click();
      await page.getByRole("button", { name: "Ср", exact: true }).click();
      await expectNoHorizontalOverflow(page, "Add to plan: выбор дня");
      const created = page.waitForResponse(
        (response) => response.url().endsWith("/api/v2/plan-items") && response.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Добавить", exact: true }).click();
      expect((await created).status()).toBe(200);

      // Вернулись на «Планы» — текущая неделя содержит новую строку...
      await expect(label).toHaveText(currentLabel);
      await expect(counters).toHaveCount(1);
      await expectNoHorizontalOverflow(page, "Plans: после добавления");

      // ...а будущая неделя осталась пустой.
      await next.click();
      await expect(label).not.toHaveText(currentLabel);
      await expect(counters).toHaveCount(0);
      await expect(page.getByText("На эту неделю пока ничего не запланировано.")).toBeVisible();

      expect(consoleErrors).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
