import { expect, test } from "@playwright/test";

import { finishV2, logMaxTimeV2, noWakeLock, playSetsV2 } from "../fixtures/builderFlow";
import { openAppAs } from "../fixtures/setup";

// scripts/e2e_seed.py journal_combined 900018 — один пользователь: legacy
// Workout запись (10 дней назад) + реальная STEP-программа "Подтягивания"
// + manual "Планка"/"Отжимания" по дням, готовые к Start. Ни одна v2-сессия
// ещё не начата — Golden Journey проходит их вживую. НЕ admin-only.
const TELEGRAM_ID = 900_018;

test("Планы → Подтягивания/Планка → Complete → Журнал показывает обе + legacy не пропала", async ({ page }) => {
  const { consoleErrors, apiFailures } = await openAppAs(page, TELEGRAM_ID);

  // Журнал показывает месяц (#263): legacy-запись «10 дней назад» живёт в предыдущем месяце
  // (или в текущем, если «сегодня» ≥ 11-е число) — листаем назад, пока она не найдётся.
  async function expectLegacyInPreviousMonth() {
    const legacy = page.locator('.history-card[data-kind="legacy"]');
    await expect(page.getByText("Загружаю историю…")).toHaveCount(0);
    if (await legacy.count() === 0) {
      await page.getByRole("button", { name: "Предыдущий месяц" }).click();
    }
    await expect(legacy.getByText("Объём", { exact: false })).toBeVisible();
  }

  await page.getByRole("button", { name: "Планы" }).click();

  // --- Подтягивания: оба блока в одной Session ---
  // #304: «Подтягивания» × 3 — три занятия; стартуем первое.
  await page.locator(".plan-week-day-group", { hasText: "Подтягивания" })
    .getByRole("button", { name: /^Начать: / }).first().click();
  const pullupsStartPromise = page.waitForResponse(
    (response) => response.url().includes("/api/v2/sessions/live") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  const pullupsStarted = await pullupsStartPromise.then((r) => r.json());
  expect(pullupsStarted.blocks).toHaveLength(2);

  // issue #306 (Live Engine v2): блок A (3) → отдых блока → блок Б (1) без «Готов»/«Пропустить отдых».
  await playSetsV2(page, ["10", "9", "11", "3"]);
  await finishV2(page);
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();

  // --- Планка ---
  await page.getByRole("button", { name: "Планы" }).click();
  await page.locator(".plan-week-day-group", { hasText: "Планка" })
    .getByRole("button", { name: /^Начать: / }).click();
  await expect(page.getByText("Планка")).toBeVisible();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await logMaxTimeV2(page, "30");
  await finishV2(page, { early: true });
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();

  // --- Журнал: обе новые + legacy не пропала ---
  const journalResponsePromise = page.waitForResponse(
    (response) => response.url().includes("status=completed") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Журнал" }).click();
  const journal = await journalResponsePromise.then((r) => r.json());

  const titles = journal.sessions.map((s: { title: string | null }) => s.title);
  expect(titles).toContain("Подтягивания");
  expect(titles).toContain("Планка");

  await expect(page.getByText("Подтягивания", { exact: true })).toBeVisible();
  await expect(page.getByText("Планка", { exact: true })).toBeVisible();
  await expect(page.getByText("Блок A", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Блок Б", { exact: true })).toHaveCount(0);
  await expectLegacyInPreviousMonth(); // legacy запись не пропала

  // --- Reload: всё то же самое из backend ---
  await page.reload({ waitUntil: "networkidle" });
  const reloadJournalPromise = page.waitForResponse(
    (response) => response.url().includes("status=completed") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Журнал" }).click();
  await reloadJournalPromise;
  await expect(page.getByText("Подтягивания", { exact: true })).toBeVisible();
  await expect(page.getByText("Планка", { exact: true })).toBeVisible();
  await expectLegacyInPreviousMonth();

  expect(apiFailures).toEqual([]);
  expect(noWakeLock(consoleErrors)).toEqual([]);
});
