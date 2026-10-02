import { expect, test } from "@playwright/test";

import { noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import { pressTelegramBackButton } from "../../fixtures/telegramMock";

// Owner P0 (#279) — «Факультатив — 3 минуты подтягиваний» нельзя было ни изменить, ни удалить.
// Что это за объект: завершённая TrainingSession(source=elective) в Журнале v2, перенесённая backfill-ом
// из legacy ElectiveWorkout (системное Exercise «Факультатив — …», без снимка и без PlanItem).
// Seed: scripts/e2e_seed.py owner_optional_workout — два факультатива (3 минуты: 4+3+2 = 9 повт.;
// на максимум: 12+10+8+6). Тест правит и удаляет запись, поэтому по пользователю на ширину/тему и
// на retry (id + retry).
const OWNER_USERS = { 320: { id: 999_801, theme: "light" }, 390: { id: 999_811, theme: "dark" } } as const;
const TITLE = "Факультатив — 3 минуты подтягиваний";

for (const width of WIDTHS) {
  const { id, theme } = OWNER_USERS[width as 320 | 390];
  test.describe(`Owner optional workout @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 800 } });
    test.setTimeout(90_000);

    test("факультатив в Журнале: видно → открыть → изменить → удалить", async ({ page }, testInfo) => {
      page.on("dialog", (dialog) => void dialog.accept());
      const { consoleErrors, apiFailures } = await openAppAs(page, id + testInfo.retry, { theme, backButton: true });
      await openTab(page, "Журнал");

      // 1) Видно: обе записи, у карточки — название упражнения-факультатива.
      const cards = page.locator(".history-card-clickable");
      await expect(cards).toHaveCount(2);
      const elective = cards.filter({ hasText: TITLE });
      await expect(elective).toHaveCount(1);
      await expectNoHorizontalOverflow(page, "Журнал: карточки факультативов");

      // 2) Открыть: сервер доказал безопасность → «Изменить» и «Удалить» есть; «Повторить» для
      // факультатива не предлагается; сырой упакованный JSON не показывается.
      await elective.click();
      await expect(page.getByRole("button", { name: /Изменить/ })).toBeVisible();
      await expect(page.getByRole("button", { name: /Удалить/ })).toBeVisible();
      await expect(page.getByRole("button", { name: /Повторить/ })).toHaveCount(0);
      await expect(page.getByText("Подходы: 4 · 3 · 2")).toBeVisible();
      await expect(page.getByText(/Факт: 9/)).toBeVisible();
      await expect(page.locator("body")).not.toContainText("equipment_type");
      await expect(page.locator("body")).not.toContainText("reps_sequence");
      await expectNoHorizontalOverflow(page, "Журнал: детали факультатива");

      // 3) Изменить: значение/усилие/комментарий; поля заметки (упакованные данные) в форме нет.
      await page.getByRole("button", { name: /Изменить/ }).click();
      const form = page.getByTestId("journal-edit-form");
      await expect(form).toBeVisible();
      await expect(form.getByLabel("Подход 1: значение")).toHaveValue("9");
      await expect(form.getByLabel("Подход 1: заметка")).toHaveCount(0);
      await expectNoHorizontalOverflow(page, "Журнал: форма правки факультатива");
      await form.getByLabel("Подход 1: значение").fill("10");
      await form.getByLabel("Усилие тренировки").selectOption({ label: "4 Тяжело" });
      await form.getByLabel("Комментарий к тренировке").fill("Поправил в журнале");
      await form.getByRole("button", { name: "Сохранить" }).click();
      await expect(page.getByTestId("journal-edit-form")).toHaveCount(0);

      await expect(cards).toHaveCount(2);
      await elective.click();
      await expect(page.getByText(/Факт: 10/)).toBeVisible();
      await expect(page.getByTestId("journal-workout-effort")).toContainText("4 Тяжело");
      await expect(page.getByTestId("journal-workout-comment")).toContainText("Поправил в журнале");
      // значение поправили (10 ≠ 4+3+2) — разбивка не показывается, иначе она противоречит «Факт: 10» (#283)
      await expect(page.getByText("Подходы: 4 · 3 · 2")).toHaveCount(0);

      // 4) Удалить: запись исчезает из Журнала, соседний факультатив остаётся.
      const deleteResponse = page.waitForResponse((r) => r.request().method() === "DELETE" && r.url().includes("/api/v2/sessions/"));
      await page.getByRole("button", { name: /Удалить/ }).click();
      expect((await deleteResponse).status()).toBe(204);
      await expect(cards).toHaveCount(1);
      await expect(cards.filter({ hasText: TITLE })).toHaveCount(0);
      await expect(cards.filter({ hasText: "Факультатив — подтягивания на максимум" })).toHaveCount(1);
      await expectNoHorizontalOverflow(page, "Журнал: после удаления факультатива");

      // Оставшаяся запись по-прежнему открывается (и возврат работает).
      await cards.first().click();
      await expect(page.getByRole("button", { name: /Удалить/ })).toBeVisible();
      await pressTelegramBackButton(page);
      await expect(cards).toHaveCount(1);

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
