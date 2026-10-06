import { confirmPreScreen, expect, finishAndSave, nav, playSets, test } from "../fixtures/app";

/**
 * S-OWNER-02 — qa_aged_legacy_snapshot AFTER the #301 aged-state convergence (owner acceptance 2026-10-06):
 * the account whose «Подтягивания» inclusion snapshot had no "program_items" (Week N · 0 из 0) can actually
 * TRAIN, not only see a button: Plans -> «Начать: Подтягивания…» -> pre-screen -> Live -> one set -> finish ->
 * Journal -> reload, and the plan counter moves. Run after the targeted repair (or after the first Plans open on
 * a build with the fix — the runtime converges the same way). Pure UI; nothing is created outside the product.
 */
test("S-OWNER-02 [qa_aged_legacy_snapshot]: repaired aged course week — a workout really starts and completes", async ({ qa }, testInfo) => {
  const s = await qa("qa_aged_legacy_snapshot");
  const { page } = s;

  await nav(page, "Планы").click();
  const progress = page.getByTestId("plan-week-progress").first();
  await expect(progress).toContainText("Текущая неделя");
  await expect(progress, "the owner's dead end is still there").not.toHaveText(/0 из 0/);
  const before = (await progress.innerText()).trim();

  const start = page.getByRole("button", { name: /^Начать: Подтягивания/ }).first();
  await expect(start).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("s-owner-02-plans-before.png"), fullPage: true });

  await start.click();
  await confirmPreScreen(page);
  await page.screenshot({ path: testInfo.outputPath("s-owner-02-live.png") });
  await playSets(page, ["8"]);
  await finishAndSave(page);
  await page.screenshot({ path: testInfo.outputPath("s-owner-02-summary.png") });
  await page.getByRole("button", { name: "Закрыть" }).click();

  await page.reload();
  await nav(page, "Журнал").click();
  await expect(page.locator(".history-card").filter({ hasText: "Подтягивания" }).first()).toBeVisible();

  await nav(page, "Планы").click();
  const after = page.getByTestId("plan-week-progress").first();
  await expect(after).toHaveText(/Текущая неделя · [1-9]\d* из \d+/);
  await page.screenshot({ path: testInfo.outputPath("s-owner-02-plans-after.png"), fullPage: true });
  await testInfo.attach("s-owner-02-summary.json", {
    body: JSON.stringify({ progressBefore: before, progressAfter: (await after.innerText()).trim() }, null, 2),
    contentType: "application/json",
  });

  await s.relaunch();
  await nav(page, "Планы").click();
  await expect(page.getByTestId("plan-week-progress").first()).toHaveText(/Текущая неделя · [1-9]\d* из \d+/);

  s.assertClean();
});
