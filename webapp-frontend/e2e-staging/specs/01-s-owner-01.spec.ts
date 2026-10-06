import { expect, nav, test, type QaSession } from "../fixtures/app";

/**
 * S-OWNER-01 — qa_aged_active: the owner's situation. «Подтягивания» was included ~3-4 weeks ago, Plans was
 * last opened in week 1, the CURRENT plan week does not exist yet and is created by the product on first open.
 *
 * EXPECT  current week has >= 1 actionable course row with a Start path, OR explicit rest-week text.
 * FORBID  «0 из 0» + «На эту неделю пока ничего не запланировано.» with no way forward (the owner's failure).
 * Evidence: screenshot + the /api/v2/plan JSON the UI actually received (attached to the report).
 */
async function assertPlansAreActionable(qa: QaSession) {
  const { page } = qa;
  await nav(page, "Планы").click();
  const progress = page.getByTestId("plan-week-progress");
  await expect(progress).toBeVisible();
  await expect(progress).toContainText("Текущая неделя");

  const text = (await progress.innerText()).trim();
  const emptyText = page.getByText("На эту неделю пока ничего не запланировано.");
  const startButtons = page.getByRole("button", { name: /^Начать: / });
  const restText = page.getByText("По плану на этой неделе отдых — тренировок нет.");

  const looksEmpty = /0 из 0/.test(text) && (await emptyText.count()) > 0;
  expect(looksEmpty, `DEAD END: "${text}" + empty-week text, no way forward`).toBe(false);

  const starts = await startButtons.count();
  const rest = (await restText.count()) > 0 || /Неделя отдыха/.test(text);
  expect(starts > 0 || rest, `current week is neither actionable nor an explicit rest week (progress: "${text}")`).toBe(true);
  return { text, starts, rest, startButtons };
}

// qa_aged_legacy_snapshot = same account whose inclusion snapshot has no "program_items" (pre-checkpoint-1.1 backfill
// shape, commit cd2808f) — the reproduction of the owner's «0 из 0». A failure there is the expected finding.
for (const identity of ["qa_aged_active", "qa_aged_legacy_snapshot"] as const) {
test(`S-OWNER-01 [${identity}]: current plan week is actionable (or an explicit rest week)`, async ({ qa }, testInfo) => {
  const s = await qa(identity);
  const { page } = s;

  const first = await assertPlansAreActionable(s);
  await page.screenshot({ path: testInfo.outputPath(`s-owner-01-${identity}-plans.png`), fullPage: true });
  await testInfo.attach(`s-owner-01-${identity}-plans.png`, { path: testInfo.outputPath(`s-owner-01-${identity}-plans.png`), contentType: "image/png" });

  // What the server said about the current week (captured from the UI's own request).
  const plan = s.lastPlanJson() as { plan?: { weeks?: Array<{ week_number: number; start_date: string }> } } | null;
  expect(plan, "the UI never received /api/v2/plan").not.toBeNull();
  await testInfo.attach(`s-owner-01-${identity}-summary.json`, {
    body: JSON.stringify({ progress: first.text, startButtons: first.starts, restWeek: first.rest, weeks: plan?.plan?.weeks?.map((w) => w.week_number) }, null, 2),
    contentType: "application/json",
  });

  // The Start path must really lead somewhere (pre-screen), not just render a button.
  if (first.starts > 0) {
    await first.startButtons.first().click();
    await expect(page.getByRole("button", { name: "Начать", exact: true })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`s-owner-01-${identity}-prescreen.png`) });
    await testInfo.attach(`s-owner-01-${identity}-prescreen.png`, { path: testInfo.outputPath(`s-owner-01-${identity}-prescreen.png`), contentType: "image/png" });
  }

  // Server state, not a client-side artefact: still actionable after a reload and a fresh launch.
  await page.reload();
  await expect(page.locator(".bottom-tabbar")).toBeVisible();
  await assertPlansAreActionable(s);
  await s.relaunch();
  await assertPlansAreActionable(s);

  s.assertClean();
});
}
