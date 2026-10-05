// B-fresh-catalog exploration helper (audit only).
import { chromium } from "/home/user/pullup-trainer-bot/webapp-frontend/e2e/node_modules/@playwright/test/index.mjs";
import { createHmac } from "node:crypto";
import fs from "node:fs";
export const BASE = "http://127.0.0.1:8092";
export const OUT = "/home/user/pullup-trainer-bot/docs/audit/wave1/B-fresh-catalog/artifacts";
const TOKEN = "audit-token";
export function initData(id, firstName = "Audit") {
  const f = { user: JSON.stringify({ id, first_name: firstName }), auth_date: String(Math.floor(Date.now() / 1000)), query_id: "AAEAAAAAAAAA" };
  const dcs = Object.keys(f).sort().map(k => `${k}=${f[k]}`).join("\n").replace(/\//g, "\\/");
  const sk = createHmac("sha256", "WebAppData").update(TOKEN).digest();
  f.hash = createHmac("sha256", sk).update(dcs).digest("hex");
  return Object.keys(f).map(k => `${k}=${encodeURIComponent(f[k])}`).join("&");
}
const initScript = ({ raw, scheme }) => {
  try { sessionStorage.setItem('tapps/launchParams', JSON.stringify(new URLSearchParams({tgWebAppPlatform:'ios',tgWebAppThemeParams:'{}',tgWebAppVersion:'7.0'}).toString())); } catch(e){}
  window.TelegramWebviewProxy = { postEvent(){} };
  window.__tgCalls = [];
  window.Telegram = { WebApp: { initData: raw, initDataUnsafe: {}, version: "7.0", platform: "ios", colorScheme: scheme, themeParams: {},
    isVersionAtLeast: () => true, ready() {}, expand() {}, close() {}, setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {},
    disableVerticalSwipes() {}, enableClosingConfirmation() {}, disableClosingConfirmation() {}, onEvent() {}, offEvent() {},
    HapticFeedback: { impactOccurred() {}, notificationOccurred() {}, selectionChanged() {} } } };
};
export async function ctxFor(browser, id, { scheme = "light" } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, colorScheme: scheme });
  await ctx.route("https://telegram.org/js/telegram-web-app.js", r => r.fulfill({ status: 200, contentType: "application/javascript", body: "" }));
  await ctx.addInitScript(initScript, { raw: initData(id), scheme });
  return ctx;
}
export class Sess {
  constructor(name, id, opts = {}) { this.name = name; this.id = id; this.opts = opts; this.log = []; this.n = 0; }
  async start() {
    this.browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome" });
    this.ctx = await ctxFor(this.browser, this.id, this.opts);
    this.page = await this.ctx.newPage(); this.hook(this.page);
    return this;
  }
  hook(page) {
    page.on("console", m => { if (["error", "warning"].includes(m.type())) this.ev(`CONSOLE ${m.type()} ${m.text().slice(0, 300)}`); });
    page.on("pageerror", e => this.ev(`PAGEERROR ${String(e).slice(0, 300)}`));
    page.on("response", async r => {
      const u = r.url(); if (!u.includes("/api/")) return;
      const m = r.request().method(); const s = r.status();
      if (m !== "GET" || s >= 400) { let b = ""; try { b = (await r.text()).slice(0, 300); } catch {} this.ev(`NET ${m} ${u.replace(BASE, "")} -> ${s} ${s >= 400 ? b : ""}`); }
    });
  }
  ev(s) { const t = new Date().toISOString().slice(11, 19); const line = `${t} ${s}`; this.log.push(line); console.log(line); }
  async open(path = "/") { await this.page.goto(BASE + path); await this.settle(); this.ev(`OPEN ${path}`); }
  async settle(ms = 1200) { await this.page.waitForLoadState("networkidle").catch(() => {}); await this.page.waitForTimeout(ms); }
  async shot(label) { this.n++; const p = `${OUT}/${this.name}-${String(this.n).padStart(2, "0")}-${label}.png`; await this.page.screenshot({ path: p }); this.ev(`SHOT ${p.split("/").pop()}`); return p; }
  async text() { return (await this.page.evaluate(() => document.body.innerText)).replace(/\n{2,}/g, "\n"); }
  async dump(label = "") { const t = await this.text(); this.ev(`VISIBLE[${label}] ${t.replace(/\n/g, " | ").slice(0, 900)}`); return t; }
  async tap(locOrText, label) { const l = typeof locOrText === "string" ? this.page.getByText(locOrText, { exact: false }).first() : locOrText; this.ev(`TAP ${label ?? locOrText}`); await l.click({ timeout: 8000 }); await this.settle(800); }
  async reload() { await this.page.reload(); await this.settle(); this.ev("RELOAD"); }
  async newCtx() { await this.ctx.close(); this.ctx = await ctxFor(this.browser, this.id, this.opts); this.page = await this.ctx.newPage(); this.hook(this.page); await this.open("/"); this.ev("NEW CONTEXT same initData id"); }
  async end() { fs.appendFileSync(`${OUT}/${this.name}.log`, this.log.join("\n") + "\n"); await this.browser.close(); }
}
export async function onboard(s, reps = "8") {
  const p = s.page; await s.open("/");
  await p.locator("input").first().fill(reps); await s.tap(p.getByRole("button",{name:"Далее"}),"Далее");
  await s.tap(p.getByRole("button",{name:"Да",exact:true}),"Да");
  const cont = p.getByRole("button",{name:"Продолжить"}); if (await cont.count()) await s.tap(cont,"Продолжить");
  await p.getByLabel("Вес, кг").fill("78"); await s.tap(p.getByRole("button",{name:"Далее"}),"Далее");
  await p.getByLabel("Рост, см").fill("180"); await s.tap(p.getByRole("button",{name:"Далее"}),"Далее");
  await p.locator("select").selectOption("male"); await s.tap(p.getByRole("button",{name:"Далее"}),"Далее");
  await p.getByLabel("Дата рождения").fill("1995-05-15"); await s.tap(p.getByRole("button",{name:"Далее"}),"Далее");
  await p.locator("select").selectOption({label:"Москва (UTC+3)"}); s.ev("SELECT tz Москва");
  await s.tap(p.getByRole("button",{name:"Готово"}),"Готово");
}
