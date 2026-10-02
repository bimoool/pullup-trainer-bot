import { expect, test } from "@playwright/test";

import { noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";

// #282 — Журнал показывал перенесённые backfill-ом тренировки дважды (v2-копия + legacy-карточка).
// Seed: scripts/e2e_seed.py journal_dedupe — мигрированный пользователь (теми же функциями backfill,
// что в проде): три legacy Workout (макс. блока A = 11/12/13) → три TrainingSession; ПОСЛЕ миграции
// ещё одна legacy-тренировка (макс. 14), у которой v2-копии нет. Ожидание: каждая тренировка в
// месячной ленте ровно один раз — перенесённые только как v2-карточки, пост-миграционная — как legacy.
// Тест только читает, но по пользователю на ширину/тему и на retry (id + retry).
const USERS = { 320: { id: 999_601, theme: "light" }, 390: { id: 999_611, theme: "dark" } } as const;

for (const width of WIDTHS) {
  const { id, theme } = USERS[width as 320 | 390];
  test.describe(`Journal dedupe @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 800 } });
    test.setTimeout(60_000);

    test("перенесённые тренировки не дублируются, пост-миграционная legacy видна", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, id + testInfo.retry, { theme });
      await openTab(page, "Журнал");

      const v2Cards = page.locator(".history-card-clickable");
      const legacyCards = page.locator(".history-card:not(.history-card-clickable)");
      await expect(v2Cards.first()).toBeVisible();

      // 3 перенесённые тренировки — по одной v2-карточке; 1 пост-миграционная — одна legacy-карточка.
      await expect(v2Cards).toHaveCount(3);
      await expect(legacyCards).toHaveCount(1);
      await expect(page.locator(".history-card")).toHaveCount(4);

      // Каждая тренировка ровно один раз (макс. блока A различает записи).
      for (const max of [11, 12, 13]) {
        await expect(v2Cards.filter({ has: page.getByText(`10 · 10 · 10 · ${max}`, { exact: true }) })).toHaveCount(1);
        await expect(legacyCards.filter({ hasText: `максимум ${max}` })).toHaveCount(0);
      }
      await expect(legacyCards.filter({ hasText: "максимум 14" })).toHaveCount(1);
      await expect(v2Cards.filter({ has: page.getByText("10 · 10 · 10 · 14", { exact: true }) })).toHaveCount(0);

      // У видимой legacy-карточки действия на месте и относятся к ней же.
      await expect(legacyCards.getByRole("button", { name: /Изменить/ })).toBeVisible();
      await expect(legacyCards.getByRole("button", { name: /Удалить/ })).toBeVisible();
      await expectNoHorizontalOverflow(page, "Журнал: перенесённые + пост-миграционная");

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
