import { expect, test } from "@playwright/test";

import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";

// Plans overview (#266). Seed: scripts/e2e_seed.py plans_overview — у пользователя в плане
// «Обзор: курс» (config.duration_weeks=8) и «Обзор: на удаление», уже завершён «Обзор: прошлый»;
// в каталоге есть «Обзор: превью» (строки есть) и «Обзор: без расписания» (строк нет).
// 9901xx — только чтение; 9902xx — мутирующий сценарий «Убрать курс из плана».
const READ_USERS = { 320: { id: 990_101, theme: "light" }, 390: { id: 990_102, theme: "dark" } } as const;
const MUTATE_USERS = { 320: { id: 990_201, theme: "light" }, 390: { id: 990_202, theme: "dark" } } as const;

for (const width of WIDTHS) {
  const read = READ_USERS[width as 320 | 390];
  const mutate = MUTATE_USERS[width as 320 | 390];

  test.describe(`Plans overview @${width}px ${read.theme}`, () => {
    test.use({ viewport: { width, height: 760 } });

    test("«Сейчас»: карточка плана с неделей курса и прогрессом; «Завершённые»: убранный курс с датами", async ({ page }) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, read.id, { theme: read.theme });
      await openTab(page, "Планы");

      await expect(page.getByRole("tab", { name: "Сейчас" })).toHaveAttribute("aria-selected", "true");
      const card = page.getByTestId("plans-now-card");
      await expect(card).toBeVisible();
      await expect(page.getByTestId("plans-now-inclusion")).toHaveCount(2);

      // Курс с длиной: «Неделя N из 8»; курс без длины — без номера недели (не выдумываем).
      const course = page.getByTestId("plans-now-inclusion").filter({ hasText: "Обзор: курс" });
      await expect(course).toContainText("Неделя 1 из 8");
      await expect(course.getByTestId("plans-now-progress")).toHaveText("На этой неделе: 0 из 6");
      const removable = page.getByTestId("plans-now-inclusion").filter({ hasText: "Обзор: на удаление" });
      await expect(removable).not.toContainText("Неделя");
      await expect(removable.getByTestId("plans-now-progress")).toHaveText("На этой неделе: 0 из 1");

      // Ниже карточки — недельный вид.
      await expect(page.getByTestId("plan-week-stepper")).toBeVisible();
      await expectNoHorizontalOverflow(page, "Plans overview: Сейчас");

      await page.getByRole("tab", { name: "Завершённые" }).click();
      const rows = page.getByTestId("plans-completed-row");
      await expect(rows).toHaveCount(1);
      await expect(rows.first()).toContainText("Обзор: прошлый");
      await expect(rows.first()).toContainText(/\d{1,2} [а-я]{3} \d{4} – \d{1,2} [а-я]{3} \d{4}/);
      await expect(page.getByTestId("plans-now-card")).toHaveCount(0);
      await expect(page.getByTestId("plan-week-stepper")).toHaveCount(0);
      await expectNoHorizontalOverflow(page, "Plans overview: Завершённые");

      expect(consoleErrors).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("детали программы: расписание из ProgramItem с фазами; без строк — только описание", async ({ page }) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, read.id, { theme: read.theme });

      await page.locator(".program-card-button").filter({ hasText: "Обзор: превью" }).click();
      await expect(page.getByTestId("program-detail-title")).toHaveText("Обзор: превью");
      const schedule = page.getByTestId("program-schedule");
      await expect(schedule).toBeVisible();
      await expect(schedule).toContainText("Расписание · 4 нед.");
      await expect(page.getByTestId("program-schedule-phase-chip")).toHaveText(["База", "Пик"]);
      const rows = page.getByTestId("program-schedule-row");
      await expect(rows).toHaveCount(3);
      await expect(rows.nth(0)).toHaveText("Понедельник · Отжимания — 2 раза в неделю");
      await expect(rows.nth(1)).toHaveText("Четверг · Планка — 1 раз в неделю");
      await expect(rows.nth(2)).toHaveText("Планка — 2 раза в неделю");
      await expect(page.getByRole("button", { name: "Добавить в план" })).toBeEnabled();
      await expectNoHorizontalOverflow(page, "Program detail: расписание");

      await page.getByRole("button", { name: "← Назад" }).click();
      await page.locator(".program-card-button").filter({ hasText: "Обзор: без расписания" }).click();
      await expect(page.getByTestId("program-detail-title")).toHaveText("Обзор: без расписания");
      await expect(page.getByText("цель: Обзор: без расписания")).toBeVisible();
      await expect(page.getByTestId("program-schedule")).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Добавить в план" })).toBeEnabled();

      expect(consoleErrors).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });

  test.describe(`Plans overview remove @${width}px ${mutate.theme}`, () => {
    test.use({ viewport: { width, height: 760 } });

    test("«Убрать курс из плана»: подтверждение, курс уходит из «Сейчас» и появляется в «Завершённых»", async ({ page }) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, mutate.id, { theme: mutate.theme });
      await openTab(page, "Планы");

      const removable = page.getByTestId("plans-now-inclusion").filter({ hasText: "Обзор: на удаление" });
      await expect(page.getByTestId("plans-now-inclusion").first()).toBeVisible();
      // Повторный прогон (CI retry) видит уже убранный курс — шаги удаления тогда пропускаются.
      if ((await removable.count()) > 0) {
        await removable.getByRole("button", { name: "Убрать курс из плана" }).click();
        await expect(page.getByText("Убрать курс «Обзор: на удаление» из плана?")).toBeVisible();
        await page.getByRole("button", { name: "Отмена" }).click();
        await expect(removable).toHaveCount(1);

        await removable.getByRole("button", { name: "Убрать курс из плана" }).click();
        await expectNoHorizontalOverflow(page, "Plans overview: подтверждение");
        await page.getByRole("button", { name: "Убрать", exact: true }).click();
        await expect(removable).toHaveCount(0);
      }
      await expect(page.getByTestId("plans-now-inclusion")).toHaveCount(1);

      await page.getByRole("tab", { name: "Завершённые" }).click();
      await expect(page.getByTestId("plans-completed-row")).toHaveCount(2);
      await expect(page.getByTestId("plans-completed-row").first()).toContainText("Обзор: на удаление");

      // Сохраняется после перезагрузки (is_active=false на сервере) и в каталоге снова можно добавить.
      await page.reload();
      await openTab(page, "Планы");
      await expect(page.getByTestId("plans-now-inclusion")).toHaveCount(1);
      await openTab(page, "Главная");
      await page.locator(".program-card-button").filter({ hasText: "Обзор: на удаление" }).click();
      await expect(page.getByRole("button", { name: "Добавить в план" })).toBeEnabled();

      expect(consoleErrors).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
