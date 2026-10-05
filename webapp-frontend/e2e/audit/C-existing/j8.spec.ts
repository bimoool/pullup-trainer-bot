import { test } from "@playwright/test";
import { execSync } from "node:child_process";
import { Log, open, shot, body, tab, liveSets } from "./lib";

test("J8 interruption (audit_interrupt)", async ({ browser }) => {
  const log = new Log("J8_audit_interrupt");
  const tg = 7300010;
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, baseURL: "http://127.0.0.1:8093" });
  const page = await ctx.newPage();
  const sql = (q: string) => execSync(`PGPASSWORD=pullup psql -h localhost -U pullup -d pullup_audit_c -tAc "${q}"`).toString().trim();
  try {
    log.add("JOURNEY", "J8 Interruption  PROFILE audit_interrupt (tg 7300010)");
    await open(page, tg, log);
    await page.waitForTimeout(2500);
    await tab(page, "Планы");
    await page.getByRole("button", { name: "Начать" }).first().click(); await page.waitForTimeout(2500);
    await page.getByRole("button", { name: "Начать" }).last().click(); await page.waitForTimeout(3500);
    await liveSets(page, log, 1, 10);
    // a) reload mid-live
    log.add("RELOAD", "mid-Live (rest phase after set 1)");
    await page.reload(); await page.waitForTimeout(3500);
    const a = await body(page);
    log.add("EXPECT", "Live resumed, set 1 preserved");
    log.add("ACTUAL", a.slice(0, 300), /ЖИВАЯ ТРЕНИРОВКА/.test(a) && /Подход 1: 10/.test(a) ? "OK" : "FAIL F-C-J8a");
    await shot(page, log, "j8_01_reload");
    // b) browser back
    log.add("TAP", "browser Back during Live");
    await page.goBack().catch(() => log.add("INFO", "goBack: no history entry"));
    await page.waitForTimeout(2000);
    const b = await body(page);
    log.add("VISIBLE", `url=${page.url()} :: ` + b.slice(0, 250));
    log.add("EXPECT", "still in Live (or confirm), session not lost");
    if (page.url() === "about:blank" || !b) { await page.goto("/"); await page.waitForTimeout(3500); }
    const b2 = await body(page);
    log.add("ACTUAL", b2.slice(0, 250), /ЖИВАЯ ТРЕНИРОВКА/.test(b2) ? "OK(session recoverable)" : "FAIL F-C-J8b session lost after back");
    // c) offline set submission
    await page.getByRole("button", { name: "Пропустить отдых" }).click({ timeout: 5000 }).catch(() => {});
    await page.getByRole("button", { name: "Готов", exact: true }).click({ timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(500);
    log.add("OFFLINE", "context.setOffline(true); enter 10 reps; Готово");
    await ctx.setOffline(true);
    await page.getByLabel("Повторений").fill("10", { timeout: 8000 }).catch((e) => log.add("INFO", "no reps field: " + String(e).slice(0, 80)));
    await page.getByRole("button", { name: "Готово", exact: true }).click({ timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(2000);
    const off = await body(page);
    log.add("VISIBLE", "offline after Готово :: " + off.slice(0, 300));
    await shot(page, log, "j8_02_offline");
    log.add("EXPECT", "set accepted locally (queued) without error screen");
    log.add("ACTUAL", off.slice(0, 250), /Подход 2: 10|ОТДЫХ|офлайн|Нет сети/i.test(off) ? "OK" : "NOTE check screenshot");
    await ctx.setOffline(false);
    await page.waitForTimeout(6000);
    log.add("ONLINE", "reconnected; waiting for sync");
    const setsAfterOnline = sql("select count(*) from set_logs sl join training_sessions ts on ts.id=sl.session_id join users u on u.id=ts.user_id where u.telegram_id=7300010 and ts.status='started'");
    log.add("DOMAIN", `set_logs of started session after reconnect = ${setsAfterOnline} (expected 2)`, setsAfterOnline === "2" ? "OK" : "FAIL F-C-J8c offline set not synced");
    await page.reload(); await page.waitForTimeout(3500);
    const c = await body(page);
    log.add("VISIBLE", "after reload :: " + c.slice(0, 300));
    // d) double-tap Finish
    await page.getByRole("button", { name: "Завершить" }).click(); await page.waitForTimeout(1000);
    await page.getByRole("button", { name: /^3/ }).click();
    log.add("TAP", "double-tap 'Сохранить и завершить'");
    await page.getByRole("button", { name: "Сохранить и завершить" }).dblclick();
    await page.waitForTimeout(3500);
    log.add("VISIBLE", "after dbl finish :: " + (await body(page)).slice(0, 300));
    await page.reload(); await page.waitForTimeout(3000);
    const n = sql("select count(*) from training_sessions ts join users u on u.id=ts.user_id where u.telegram_id=7300010 and ts.performed_at::date=current_date");
    log.add("EXPECT", "exactly 1 session today for user");
    log.add("ACTUAL", `training_sessions today = ${n}`, n === "1" ? "OK" : "FAIL F-C-J8d duplicate session");
    await tab(page, "Журнал");
    const j = await body(page);
    log.add("VISIBLE", "Журнал :: " + j.slice(0, 350));
    const entries = (j.match(/По плану/g) || []).length;
    log.add("EXPECT", "one 'По плану' entry");
    log.add("ACTUAL", `entries=${entries}`, entries === 1 ? "OK" : "FAIL F-C-J8d");
    await shot(page, log, "j8_03_final");
  } finally { log.flush(); await ctx.close(); }
});
