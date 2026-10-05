import { expect, test } from "@playwright/test";

import { noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";

// #282/#284 — Журнал показывал перенесённые backfill-ом тренировки дважды (v2-копия + legacy-карточка).
// Правильное направление (#284): старая схема — источник правды для перенесённой истории, поэтому
// показываются ВСЕ legacy-карточки (только у них есть «Изменить»/«Удалить»), а v2-копии,
// созданные backfill-ом, скрыты.
// Seed: scripts/e2e_seed.py journal_dedupe — мигрированный пользователь (теми же функциями backfill,
// что в проде): три legacy Workout (макс. блока A = 11/12/13) → три TrainingSession; ПОСЛЕ миграции
// ещё одна legacy-тренировка (макс. 14), у которой v2-копии нет.
// Тест МУТИРУЕТ данные (правка и удаление) — пользователь на ширину/тему и на retry (id + retry).
const USERS = { 320: { id: 999_601, theme: "light" }, 390: { id: 999_611, theme: "dark" } } as const;

for (const width of WIDTHS) {
  const { id, theme } = USERS[width as 320 | 390];
  test.describe(`Journal dedupe @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 800 } });
    test.setTimeout(90_000);

    test("каждая тренировка один раз, у карточек есть действия; правка и удаление работают", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, id + testInfo.retry, { theme });
      await openTab(page, "Журнал");

      const v2Cards = page.locator(".history-card-clickable");
      const legacyCards = page.locator(".history-card:not(.history-card-clickable)");
      const legacyCard = (max: number) => legacyCards.filter({ hasText: `максимум ${max}` });
      await expect(legacyCards.first()).toBeVisible();

      // Все 4 тренировки — по одной legacy-карточке; backfill-копий (v2-карточек) нет.
      await expect(legacyCards).toHaveCount(4);
      await expect(v2Cards).toHaveCount(0);
      await expect(page.locator(".history-card")).toHaveCount(4);
      for (const max of [11, 12, 13, 14]) {
        await expect(legacyCard(max)).toHaveCount(1);
        // У каждой карточки (в том числе перенесённой) есть действия, относящиеся к ней же.
        await expect(legacyCard(max).getByRole("button", { name: /Изменить/ })).toBeVisible();
        await expect(legacyCard(max).getByRole("button", { name: /Удалить/ })).toBeVisible();
      }
      await expect(page.getByRole("button", { name: /Изменить/ })).toHaveCount(4);
      await expect(page.getByRole("button", { name: /Удалить/ })).toHaveCount(4);
      await expectNoHorizontalOverflow(page, "Журнал: перенесённые + пост-миграционная");

      // Правка перенесённой тренировки (макс. 12 → 15): новое значение видно, старое — нет, дубля нет.
      await legacyCard(12).getByRole("button", { name: /Изменить/ }).click();
      await page.getByLabel("Блок A, подход на максимум").fill("15");
      await page.getByRole("button", { name: "Сохранить", exact: true }).click();
      const confirm = page.getByRole("button", { name: "Всё верно" });
      const done = page.getByRole("button", { name: "Готово" });
      await expect(confirm.or(done)).toBeVisible();
      if (await confirm.isVisible()) {
        await confirm.click();
      }
      await done.click();
      await openTab(page, "Журнал");
      await expect(legacyCard(15)).toHaveCount(1);
      await expect(legacyCard(12)).toHaveCount(0);
      await expect(legacyCards).toHaveCount(4);
      await expect(v2Cards).toHaveCount(0);

      // Удаление перенесённой тренировки (макс. 13): исчезает, и копия не «воскресает».
      page.once("dialog", (dialog) => void dialog.accept());
      await legacyCard(13).getByRole("button", { name: /Удалить/ }).click();
      await expect(legacyCard(13)).toHaveCount(0);
      await expect(legacyCards).toHaveCount(3);
      await expect(v2Cards).toHaveCount(0);
      await expect(page.locator(".history-card")).toHaveCount(3);
      for (const max of [11, 14, 15]) {
        await expect(legacyCard(max)).toHaveCount(1);
      }
      await expectNoHorizontalOverflow(page, "Журнал: после правки и удаления");

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
