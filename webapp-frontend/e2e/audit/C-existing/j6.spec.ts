import { test } from "@playwright/test";
import { execSync } from "node:child_process";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
import { Log, open, shot, body, tab, trainOnce } from "./lib";
const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../..");

async function afterRelaunch(page: any, log: Log, label: string) {
  await page.reload(); await page.waitForTimeout(3000);
  await tab(page, "Журнал");
  const j = await body(page);
  log.add("VISIBLE", `Журнал(${label}) :: ` + j.slice(0, 300));
  return j;
}

for (const [name, tg] of [["audit_trial", 7300004], ["audit_trial_rested", 7300007], ["audit_active_paid", 7300005]] as const) {
  test(`J6 ${name} can train`, async ({ page }) => {
    const log = new Log(`J6_${name}`);
    try {
      log.add("JOURNEY", `J6 Subscription: ${name} must be able to start and complete (tg ${tg})`);
      await open(page, tg, log);
      await page.waitForTimeout(2500);
      await tab(page, "Профиль");
      log.add("VISIBLE", "Профиль :: " + (await body(page)).slice(0, 500));
      await shot(page, log, "profile");
      const r = await trainOnce(page, log, 2);
      log.add("EXPECT", "training completed (summary 'Тренировка завершена')");
      log.add("ACTUAL", r.ok ? "completed" : "not completed", r.ok ? "OK" : "FAIL F-C-xx");
      const j = await afterRelaunch(page, log, "after reload");
      log.add("EXPECT", "new session in Журнал after reload");
      log.add("ACTUAL", j.slice(0, 200), /Подтягивания/.test(j) ? "OK" : "FAIL");
      await shot(page, log, "journal_after");
    } finally { log.flush(); }
  });
}

test("J6 audit_expired: paywall, then admin grant", async ({ page }) => {
  const log = new Log("J6_audit_expired");
  const tg = 7300006;
  try {
    log.add("JOURNEY", "J6 Subscription: audit_expired (tg 7300006; trial ended 26 days ago, cache still 'trial' as the bot never flips it)");
    await open(page, tg, log);
    await page.waitForTimeout(2500);
    await tab(page, "Профиль");
    log.add("VISIBLE", "Профиль :: " + (await body(page)).slice(0, 600));
    await shot(page, log, "01_profile_expired");
    await tab(page, "Планы");
    const p0 = await body(page);
    log.add("EXPECT", "clear paywall / no_access that blocks starting");
    log.add("ACTUAL", p0.slice(0, 450), /Нет активной подписки/.test(p0) ? "OK(banner shown)" : "FAIL F-C-02 no paywall banner");
    await shot(page, log, "02_plans_expired");
    log.add("EXPECT", "Начать is disabled / absent for expired user");
    const canStart = (await page.getByRole("button", { name: "Начать" }).count()) > 0;
    log.add("ACTUAL", canStart ? "Начать present+enabled" : "absent", canStart ? "FAIL F-C-02 start not gated by subscription" : "OK");
    const r = await trainOnce(page, log, 2);
    log.add("ACTUAL", r.ok ? "expired user COMPLETED a workout" : "blocked", r.ok ? "FAIL F-C-02 (v2 live path ignores subscription)" : "OK");
    await shot(page, log, "03_after_expired_train");
    // state before grant
    await page.reload(); await page.waitForTimeout(2500);
    await tab(page, "Планы");
    const before = await body(page);
    log.add("VISIBLE", "STATE BEFORE GRANT Планы :: " + before.slice(0, 450));
    await tab(page, "Журнал");
    const jBefore = await body(page);
    log.add("VISIBLE", "STATE BEFORE GRANT Журнал :: " + jBefore.slice(0, 300));
    await tab(page, "Профиль");
    log.add("VISIBLE", "STATE BEFORE GRANT Профиль :: " + (await body(page)).slice(0, 500));
    // ---- admin grant through the bot handler (feed_update) ----
    const out = execSync(`cd ${REPO} && BOT_TOKEN=audit-token DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:5432/pullup_audit_c REDIS_URL=redis://localhost:6379/3 PYTHONPATH=. .venv/bin/python scripts/audit/c_admin_grant.py ${tg} 30 2>&1 | tail -5`).toString();
    log.add("ADMIN", "grant via bot handler admin_grant_days + feed_update (Dispatcher) :: " + out.replace(/\n/g, " | "));
    await page.reload(); await page.waitForTimeout(3000);
    await tab(page, "Планы");
    const after = await body(page);
    log.add("VISIBLE", "STATE AFTER GRANT Планы :: " + after.slice(0, 450));
    log.add("EXPECT", "banner 'Нет активной подписки' gone; plan counters preserved");
    log.add("ACTUAL", after.slice(0, 450), !/Нет активной подписки/.test(after) ? "OK" : "FAIL F-C-04 banner persists after grant");
    await shot(page, log, "04_plans_after_grant");
    await tab(page, "Журнал");
    const jAfter = await body(page);
    log.add("EXPECT", "Журнал unchanged by grant");
    log.add("ACTUAL", jAfter.slice(0, 300), jAfter === jBefore ? "OK" : "FAIL (diff)");
    await tab(page, "Профиль");
    log.add("VISIBLE", "STATE AFTER GRANT Профиль :: " + (await body(page)).slice(0, 500));
    await shot(page, log, "05_profile_after_grant");
    log.add("INFO", "second training after grant not attempted for this profile: MIN_REST_DAYS (valid rule) blocks a 2nd session the same day; covered by audit_expired_b");
  } finally { log.flush(); }
});

test("J6 audit_expired_b: paywall -> admin grant -> train", async ({ page }) => {
  const log = new Log("J6_audit_expired_b");
  const tg = 7300008;
  try {
    log.add("JOURNEY", "J6 Subscription: audit_expired_b (tg 7300008; trial ended ~31 days ago; last workout 33 days ago) paywall -> grant -> train");
    await open(page, tg, log);
    await page.waitForTimeout(2500);
    await tab(page, "Планы");
    const p0 = await body(page);
    log.add("EXPECT", "paywall / no_access visible");
    log.add("ACTUAL", p0.slice(0, 450), /Нет активной подписки/.test(p0) ? "OK(banner)" : "FAIL");
    await shot(page, log, "01_plans_expired_b");
    await tab(page, "Журнал");
    const jBefore = await body(page);
    log.add("VISIBLE", "Журнал before grant :: " + jBefore.slice(0, 300));
    const out = execSync(`cd ${REPO} && BOT_TOKEN=audit-token DATABASE_URL=postgresql+asyncpg://pullup:pullup@localhost:5432/pullup_audit_c REDIS_URL=redis://localhost:6379/3 PYTHONPATH=. .venv/bin/python scripts/audit/c_admin_grant.py ${tg} 30 2>&1 | tail -5`).toString();
    log.add("ADMIN", "grant via bot handler admin_grant_days + feed_update :: " + out.replace(/\n/g, " | "));
    await page.reload(); await page.waitForTimeout(3000);
    await tab(page, "Планы");
    const after = await body(page);
    log.add("EXPECT", "banner gone, same plan week, no re-onboarding");
    log.add("ACTUAL", after.slice(0, 450), !/Нет активной подписки/.test(after) && /Неделя 1/.test(after) ? "OK" : "FAIL F-C-04");
    await shot(page, log, "02_plans_after_grant");
    const r = await trainOnce(page, log, 2);
    log.add("EXPECT", "after grant: start and complete");
    log.add("ACTUAL", r.ok ? "completed" : "not completed", r.ok ? "OK" : "FAIL");
    await page.reload(); await page.waitForTimeout(2500);
    const j = await afterRelaunch(page, log, "after train");
    log.add("EXPECT", "Журнал has new session");
    log.add("ACTUAL", j.slice(0, 250), /По плану/.test(j) ? "OK" : "FAIL");
  } finally { log.flush(); }
});
