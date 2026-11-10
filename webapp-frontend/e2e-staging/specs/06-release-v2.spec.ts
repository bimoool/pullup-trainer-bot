import { expect, nav, test } from "../fixtures/app";

/** Current v2 paths on the deployed staging. Reprovision QA identities before each project. */
test("R-V2 fresh: full course, pause/reload, journal and rest gate persist", async ({ qa }) => {
  const s = await qa("qa_fresh_active");
  const { page } = s;
  await nav(page, "Планы").click();
  await expect(page.getByTestId("plans-now-empty")).toBeVisible();
  await nav(page, "Главная").click();
  await page.getByRole("button", { name: /^Подтягивания/ }).first().click();
  await page.getByRole("button", { name: "Добавить в план", exact: true }).click();
  await expect(page.getByRole("button", { name: "В плане", exact: true })).toBeVisible();
  await page.reload();
  await nav(page, "Планы").click();
  await expect(page.getByTestId("plan-week-progress").first()).toHaveText(/Текущая неделя · 0 из 2/);
  await page.getByRole("button", { name: /^Начать: Подтягивания/ }).first().click();
  await expect(page.getByTestId("course-setup-required")).toBeVisible();
  await page.getByTestId("course-input-volume_capacity").fill("10");
  await page.getByTestId("course-volume-band-name").fill("QA band");
  await page.getByTestId("course-volume-band-colour").fill("blue");
  await page.getByTestId("course-volume-band-attachment").fill("bar");
  await page.getByTestId("course-volume-band-position").fill("foot");
  await page.getByTestId("course-strength-band-bodyweight").check();
  await page.getByTestId("course-setup-save").click();
  await expect(page.getByText("Блок 1: 7/7/7/7+")).toBeVisible();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  const phase = page.getByTestId("engine-phase");
  const values = ["7", "7", "7", "9", "5", "5", "5", "5", "6"];
  for (let i = 0; i < values.length; i += 1) {
    await expect(page.getByTestId("engine-saving")).toHaveCount(0);
    await expect(phase).toHaveText(/Приготовься|Отдых|Пошёл/);
    if ((await phase.textContent())?.trim() !== "Пошёл") await page.getByTestId("engine-skip").click();
    await expect(phase).toHaveText("Пошёл");
    await page.getByLabel("Результат подхода").fill(values[i]);
    await page.getByTestId("engine-submit").click();
    await expect(phase).not.toHaveText("Пошёл");
    await expect(page.getByTestId("engine-saving")).toHaveCount(0);
    await expect(page.getByTestId("engine-pending")).toHaveCount(0);
    if (i === 0) {
      await page.getByTestId("pause-toggle").click();
      await expect(phase).toHaveText("Отдых · пауза");
      await expect(page.getByTestId("engine-pending")).toHaveCount(0);
      await page.reload();
      await expect(page.getByTestId("engine-phase")).toHaveText("Отдых · пауза");
      await page.getByTestId("pause-toggle").click();
      await expect(page.getByTestId("engine-phase")).toHaveText("Отдых");
    }
  }
  await expect(page.getByTestId("engine-confirm")).toBeVisible();
  for (const group of await page.locator('[data-testid^="check-technique-"], [data-testid^="check-rest-"]').all()) {
    await group.getByRole("button", { name: "Да", exact: true }).click();
  }
  await page.getByTestId("engine-confirm-submit").click();
  await expect(page.getByTestId("engine-complete")).toBeVisible();
  await page.getByTestId("engine-save").click();
  await expect(page.getByTestId("course-progression")).toContainText("Следующая тренировка B");
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  await s.relaunch();
  await nav(page, "Журнал").click();
  await expect(page.locator(".history-card").filter({ hasText: "Подтягивания" })).toHaveCount(1);
  await nav(page, "Планы").click();
  await expect(page.getByTestId("plan-week-progress").first()).toHaveText(/Текущая неделя · 1 из 2/);
  await expect(page.getByRole("button", { name: /^Начать: Подтягивания/ })).toHaveCount(0);
  s.assertClean();
});

for (const identity of ["qa_aged_active", "qa_aged_legacy_snapshot"] as const) {
  test(`R-V2 aged ${identity}: current plan survives reload and fresh launch`, async ({ qa }) => {
    const s = await qa(identity);
    for (let pass = 0; pass < 3; pass += 1) {
      await nav(s.page, "Планы").click();
      await expect(s.page.getByTestId("plan-week-progress").first()).not.toHaveText(/0 из 0/);
      await expect(s.page.getByRole("button", { name: /^Начать: Подтягивания/ }).first()).toBeVisible();
      if (pass === 0) await s.page.reload();
      if (pass === 1) await s.relaunch();
    }
    s.assertClean();
  });
}

/** Incident fixture is synthetic; every workout event below goes to the deployed API. */
test("R-V2 incident B: 10x5 keeps one-minute rests, then +10 kg survives reload", async ({ qa }) => {
  const s = await qa("qa_weighted_b");
  const { page } = s;
  await nav(page, "Планы").click();
  await page.getByRole("button", { name: /^Начать: Подтягивания/ }).first().click();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  const phase = page.getByTestId("engine-phase");
  await expect(page.getByTestId("engine-load")).toHaveText("Свой вес");
  for (let index = 0; index < 10; index += 1) {
    await expect(page.getByTestId("engine-saving")).toHaveCount(0);
    await page.getByTestId("engine-skip").click();
    await expect(phase).toHaveText("Пошёл");
    await expect(page.getByTestId("engine-target")).toContainText(`Подход ${index + 1}/10`);
    await page.getByLabel("Результат подхода").fill("5");
    await page.getByTestId("engine-submit").click();
    await expect(phase).toHaveText("Отдых");
    await expect(page.getByTestId("engine-saving")).toHaveCount(0);
    await expect(page.getByTestId("engine-pending")).toHaveCount(0);
    // UI shows elapsed time after network/render; exact 60/900 is asserted in the API fixture test.
    await expect(page.getByTestId("engine-timer")).toHaveText(
      index < 9 ? /^(0:5[0-9]|1:00)$/ : /^(14:5[0-9]|15:00)$/,
    );
    await expect(page.getByTestId("engine-next-block")).toHaveCount(index < 9 ? 0 : 1);
    if (index === 2) {
      await page.reload();
      await expect(phase).toHaveText("Отдых");
      await expect(page.getByTestId("engine-target")).toContainText("Подход 3/10");
      await expect(page.getByTestId("engine-load")).toHaveText("Свой вес");
      await expect(page.getByTestId("engine-timer")).toHaveText(/^(0:[0-5][0-9]|1:00)$/);
      await expect(page.getByTestId("engine-next-block")).toHaveCount(0);
    }
  }
  await page.getByTestId("engine-skip").click();
  await expect(page.getByTestId("engine-load")).toHaveText("+10 кг");
  await expect(page.getByTestId("engine-target")).toContainText("Подход 1/5");
  await page.reload();
  await expect(page.getByTestId("engine-load")).toHaveText("+10 кг");
  await expect(page.getByTestId("engine-target")).toContainText("Подход 1/5");
  s.assertClean();
});

test("R-V2 incident B browser fallback 6.1: cancel preserves set; confirm ends block", async ({ qa }) => {
  const s = await qa("qa_weighted_b_stop", { version: "6.1" });
  const { page } = s;
  await nav(page, "Планы").click();
  await page.getByRole("button", { name: /^Начать: Подтягивания/ }).first().click();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await page.getByTestId("engine-skip").click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл");
  // Exercise the supported pre-6.2 client browser-confirm fallback explicitly.
  // Launch version selects the production branch; no SDK/window.confirm mocks.
  // Native Telegram 8.0 popup acceptance remains a separate real-device gate.
  const cancelled = page.waitForEvent("dialog");
  const cancelClick = page.getByTestId("engine-submit-technique-broken").click();
  const cancelDialog = await cancelled;
  expect(cancelDialog.type()).toBe("confirm");
  expect(cancelDialog.message()).toContain("Завершить весь объёмный блок");
  await cancelDialog.dismiss();
  await cancelClick;
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл");
  await expect(page.getByTestId("engine-target")).toContainText("Подход 1/10");
  await expect(page.getByTestId("engine-next-block")).toHaveCount(0);
  await page.getByLabel("Результат подхода").fill("5");
  await page.getByTestId("engine-submit").click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых");
  await expect(page.getByTestId("engine-timer")).toHaveText(/^(0:5[0-9]|1:00)$/);
  await expect(page.getByTestId("engine-next-block")).toHaveCount(0);
  await expect(page.getByTestId("engine-saving")).toHaveCount(0);
  await page.getByTestId("engine-skip").click();
  await expect(page.getByTestId("engine-target")).toContainText("Подход 2/10");
  await page.getByLabel("Результат подхода").fill("5");
  const confirmed = page.waitForEvent("dialog");
  const confirmClick = page.getByTestId("engine-submit-technique-broken").click();
  const confirmDialog = await confirmed;
  expect(confirmDialog.type()).toBe("confirm");
  await confirmDialog.accept();
  await confirmClick;
  await expect(page.getByTestId("engine-next-block")).toBeVisible();
  await expect(page.getByTestId("engine-rest-context")).toContainText("отмечено нарушение техники");
  await expect(page.getByTestId("engine-timer")).toHaveText(/^(14:5[0-9]|15:00)$/);
  s.assertClean();
});
