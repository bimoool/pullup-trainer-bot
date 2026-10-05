import { test } from "@playwright/test";
import { Log, open, shot, body, tab, expectText, liveSets } from "./lib";

const PROFILES: Record<string, number> = {
  audit_existing_active: 7300001,
  audit_legacy_existing: 7300002,
  audit_returning_week_transition: 7300003,
};

for (const [name, tg] of Object.entries(PROFILES)) {
  test(`J1 ${name}`, async ({ page }) => {
    const log = new Log(`J1_${name}`);
    try {
      log.add("JOURNEY", `J1-existing PROFILE ${name} tg=${tg}`);
      log.add("OPEN", "Home");
      await open(page, tg, log);
      await page.waitForTimeout(2500);
      await expectText(page, log, "Home with program card", /Подтягивания/, "F-C-J1-home");
      await shot(page, log, "01_home");
      log.add("TAP", "Планы");
      await tab(page, "Планы");
      await shot(page, log, "02_plans");
      const hasStart = await page.getByRole("button", { name: "Начать" }).count();
      log.add("EXPECT", ">=1 actionable workout current week (button Начать)");
      log.add("ACTUAL", (await body(page)).slice(0, 500), hasStart ? "OK" : "FAIL no-start");
      if (!hasStart) return;
      log.add("TAP", "Начать (plan row)");
      await page.getByRole("button", { name: "Начать" }).first().click();
      await page.waitForTimeout(2500);
      log.add("VISIBLE", await body(page));
      await shot(page, log, "03_ready_to_start");
      await page.getByRole("button", { name: "Начать" }).last().click();
      await page.waitForTimeout(3500);
      await expectText(page, log, "Live screen", /ЖИВАЯ ТРЕНИРОВКА/, "F-C-J1-live");
      await shot(page, log, "04_live");
      const n = await liveSets(page, log, 2, 10);
      await shot(page, log, "05_after_sets");
      log.add("TAP", "Завершить");
      await page.getByRole("button", { name: "Завершить" }).click();
      await page.waitForTimeout(1200);
      await page.getByRole("button", { name: /^3/ }).click();
      await page.getByRole("button", { name: "Сохранить и завершить" }).click();
      await page.waitForTimeout(2500);
      log.add("VISIBLE", "after finish :: " + await body(page));
      await shot(page, log, "06_summary");
      log.add("RELOAD", "after finish");
      await page.reload(); await page.waitForTimeout(3000);
      log.add("VISIBLE", await body(page));
      await shot(page, log, "07_after_reload");
      await tab(page, "Журнал");
      log.add("VISIBLE", "Журнал :: " + await body(page));
      await shot(page, log, "08_journal");
      await tab(page, "Аналитика");
      log.add("VISIBLE", "Аналитика :: " + await body(page));
      await shot(page, log, "09_analytics");
      await page.reload(); await page.waitForTimeout(2500);
      await tab(page, "Планы");
      log.add("VISIBLE", "Планы after reopen :: " + await body(page));
      await shot(page, log, "10_plans_reopen");
      log.add("INFO", `sets logged ${n}`);
    } finally { log.flush(); }
  });
}
