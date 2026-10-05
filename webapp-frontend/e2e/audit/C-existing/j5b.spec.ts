import { test } from "@playwright/test";
import { Log, open, shot, body, tab } from "./lib";

async function count(page: any, log: Log, label: string) {
  await tab(page, "Аналитика");
  const b = await body(page);
  const m = b.match(/(\d+) \| Тренировок за 30 дней/);
  log.add("VISIBLE", `Аналитика(${label}) Тренировок за 30 дней=${m?.[1]} :: ` + b.slice(0, 240));
  return m ? Number(m[1]) : -1;
}

test("J5b legacy/backfilled session (audit_legacy_existing)", async ({ page }) => {
  const log = new Log("J5b_audit_legacy_existing");
  try {
    log.add("JOURNEY", "J5b Journal lifecycle on LEGACY (bot-era, backfilled) data  PROFILE audit_legacy_existing (tg 7300002)  S0: 3 legacy workouts + 1 elective converted by backfill; J1 completed 1 native session via UI");
    await open(page, 7300002, log);
    await page.waitForTimeout(2500);
    const c0 = await count(page, log, "before");
    await tab(page, "Журнал");
    const j0 = await body(page);
    log.add("VISIBLE", "Журнал current+prev week :: " + j0.slice(0, 700));
    log.add("EXPECT", "legacy workout 02.10 listed once (backfill copy not duplicated)");
    const dup = (j0.match(/02\.10\.2026/g) || []).length;
    log.add("ACTUAL", `occurrences of 02.10.2026 = ${dup}`, dup === 1 ? "OK" : "FAIL F-C-11 duplicate/missing");
    await shot(page, log, "j5b_01_journal");
    log.add("TAP", "Изменить on legacy entry; set block A set 1 = 9");
    await page.getByRole("button", { name: "Изменить" }).first().click();
    await page.getByLabel("Блок A, подход 1").fill("9");
    await page.getByRole("button", { name: "Сохранить" }).click();
    await page.waitForTimeout(2000);
    log.add("VISIBLE", "after save :: " + (await body(page)).slice(0, 500));
    await page.reload(); await page.waitForTimeout(2500);
    await tab(page, "Журнал");
    const j1 = await body(page);
    log.add("EXPECT", "Объём (резина): 9, 10, 10 after reload");
    log.add("ACTUAL", j1.slice(0, 700), /Объём \(резина\): 9, 10, 10/.test(j1) ? "OK" : "FAIL F-C-12");
    const c1 = await count(page, log, "after edit");
    // previous-week navigation: elective + older legacy
    await tab(page, "Журнал");
    await page.getByText("‹", { exact: true }).first().click(); await page.waitForTimeout(1800);
    const prev = await body(page);
    log.add("VISIBLE", "prev week (‹) :: " + prev.slice(0, 700));
    await shot(page, log, "j5b_02_prev_week");
    // delete legacy entry (disposable = the 02.10 workout is NOT disposable data in real life; used here only because seeded)
    await page.reload(); await page.waitForTimeout(2500);
    await tab(page, "Журнал");
    log.add("TAP", "Удалить on 02.10 legacy entry");
    await page.getByRole("button", { name: "Удалить" }).first().click();
    await page.waitForTimeout(2000);
    await page.reload(); await page.waitForTimeout(2500);
    await tab(page, "Журнал");
    const j2 = await body(page);
    log.add("EXPECT", "02.10 entry gone after delete+reload");
    log.add("ACTUAL", j2.slice(0, 500), /02\.10\.2026/.test(j2) ? "FAIL F-C-13" : "OK");
    const c2 = await count(page, log, "after delete");
    log.add("INFO", `analytics before=${c0} afterEdit=${c1} afterDelete=${c2}`);
    log.add("EXPECT", "analytics count decreases by 1 after delete");
    log.add("ACTUAL", `${c1} -> ${c2}`, c2 === c1 - 1 ? "OK" : "FAIL F-C-14 analytics did not reflect delete");
    await shot(page, log, "j5b_03_final");
  } finally { log.flush(); }
});
