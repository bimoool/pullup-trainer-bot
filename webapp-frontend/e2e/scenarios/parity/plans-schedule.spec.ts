import { expect, test } from "@playwright/test";

import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";

// Plans schedule (#275). Seed: scripts/e2e_seed.py plan_week_manual_session — в текущей неделе
// два ручных PlanItem (Планка — среда, Отжимания — пятница), без программ. Мутирующий сценарий —
// свой пользователь на каждую ширину/тему: 990301 (320, light), 990302 (390, dark).
const USERS = { 320: { id: 990_301, theme: "light" }, 390: { id: 990_302, theme: "dark" } } as const;

for (const width of WIDTHS) {
  const user = USERS[width as 320 | 390];

  test.describe(`Plans schedule @${width}px ${user.theme}`, () => {
    test.use({ viewport: { width, height: 760 } });

    test("будущая неделя по › , копирование недели с подтверждением, перенос на другую неделю", async ({ page }) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, user.id, { theme: user.theme });
      await openTab(page, "Планы");

      const label = page.getByTestId("plan-week-label");
      const counters = page.getByTestId("plan-item-counter");
      const next = page.getByRole("button", { name: "Следующая неделя" });
      const prev = page.getByRole("button", { name: "Предыдущая неделя" });
      const copyButton = page.getByRole("button", { name: "Скопировать неделю → на следующую" });
      const currentLabel = (await label.textContent()) ?? "";
      await expect(counters).toHaveCount(2);

      // › за текущей неделей создаёт будущую: пустая, но редактируемая.
      await expect(next).toBeEnabled();
      await next.click();
      await expect(label).not.toHaveText(currentLabel);
      await expect(counters).toHaveCount(0);
      await expect(page.getByText("На эту неделю пока ничего не запланировано.")).toBeVisible();
      await expect(page.getByRole("button", { name: "+ Добавить упражнение" })).toBeVisible();
      await expectNoHorizontalOverflow(page, "Plans schedule: будущая неделя");
      const futureLabel = (await label.textContent()) ?? "";

      // Копирование текущей недели → следующая: с подтверждением, «Отмена» ничего не делает.
      await prev.click();
      await expect(label).toHaveText(currentLabel);
      await copyButton.click();
      await expect(page.getByText(/Скопировать свои тренировки и упражнения/)).toBeVisible();
      await page.getByRole("button", { name: "Отмена" }).click();
      await expect(copyButton).toBeVisible();
      await copyButton.click();
      await page.getByRole("button", { name: "Скопировать", exact: true }).click();
      await expect(page.getByTestId("plan-week-copy-result")).toHaveText("Скопировано: 2, пропущено дублей: 0");
      await expect(label).toHaveText(futureLabel);
      await expect(counters).toHaveCount(2);
      await expectNoHorizontalOverflow(page, "Plans schedule: после копирования");

      // Повторное копирование пропускает дубли.
      await prev.click();
      await copyButton.click();
      await page.getByRole("button", { name: "Скопировать", exact: true }).click();
      await expect(page.getByTestId("plan-week-copy-result")).toHaveText("Скопировано: 0, пропущено дублей: 2");
      await expect(counters).toHaveCount(2);

      // Перенос ручной строки из будущей недели обратно на текущую.
      await expect(label).toHaveText(futureLabel);
      await page.getByRole("button", { name: "Перенести" }).first().click();
      const picker = page.getByTestId("move-week-picker");
      await expect(picker).toBeVisible();
      await expectNoHorizontalOverflow(page, "Plans schedule: перенос");
      await picker.getByRole("button").first().click();
      await page.getByRole("button", { name: "Сохранить" }).click();
      await expect(counters).toHaveCount(1);
      await prev.click();
      await expect(label).toHaveText(currentLabel);
      await expect(counters).toHaveCount(3);

      expect(consoleErrors).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
