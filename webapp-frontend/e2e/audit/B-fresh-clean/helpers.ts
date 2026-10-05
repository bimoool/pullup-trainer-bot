import { expect, type BrowserContext, type Page, type TestInfo } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { buildInitData } from "../../fixtures/initData";
type TelegramTheme = "light" | "dark";

export const BOT_TOKEN = "audit-token";
export const ART = "/home/user/pullup-trainer-bot/docs/audit/wave1/B-fresh-clean/artifacts";

export class Trace {
  failures: string[] = [];
  lines: string[] = [];
  constructor(public name: string, public page: Page, private info: TestInfo) {
    page.on("response", async (r) => {
      if (r.url().includes("/api/") && r.status() >= 400) {
        let b = ""; try { b = (await r.text()).slice(0, 300); } catch { /* ignore */ }
        this.log(`NETFAIL ${r.status()} ${r.request().method()} ${new URL(r.url()).pathname} :: ${b}`);
      }
    });
    page.on("pageerror", (e) => this.log(`PAGEERROR ${e.message.slice(0, 200)}`));
    page.on("console", (m) => { if (m.type() === "error" && !/Telegram SDK init/.test(m.text())) this.log(`CONSOLE.error ${m.text().slice(0, 200)}`); });
  }
  log(s: string) {
    const t = new Date().toISOString().slice(11, 19);
    const line = `${t} ${s}`;
    this.lines.push(line);
    fs.mkdirSync(ART, { recursive: true });
    fs.appendFileSync(path.join(ART, `trace-${this.name}.log`), line + "\n");
  }
  async visible(): Promise<string> {
    return (await this.page.locator("body").innerText()).replace(/\s*\n+\s*/g, " | ").slice(0, 700);
  }
  async shot(label: string) { await this.page.screenshot({ path: path.join(ART, `${this.name}-${label}.png`) }); }
  async open(label: string) { this.log(`OPEN ${label}`); }
  async tap(label: string, loc: ReturnType<Page["locator"]>) { this.log(`TAP "${label}"`); await loc.first().click(); await this.page.waitForTimeout(900); }
  async reload(label = "") {
    this.log(`RELOAD ${label}`); await this.page.reload(); await this.page.waitForTimeout(2200);
  }
  /** EXPECT/ACTUAL pair. ok decides; findingId is cited on FAIL. Never throws: the run continues, failure is collected. */
  async check(expectText: string, ok: boolean, findingId: string, shotLabel?: string) {
    const actual = await this.visible();
    this.log(`EXPECT ${expectText}`);
    this.log(`ACTUAL ${actual}   ${ok ? "OK" : "FAIL " + findingId}`);
    if (!ok) { this.failures.push(`${findingId}: ${expectText}`); if (shotLabel) await this.shot(shotLabel); }
    else if (shotLabel) await this.shot(shotLabel);
    return ok;
  }
  finish() {
    this.log(`SUMMARY ${this.failures.length ? "FAIL " + JSON.stringify(this.failures) : "PASS"}`);
    this.info.annotations.push({ type: "audit-failures", description: JSON.stringify(this.failures) });
    if (this.failures.length) throw new Error(`AUDIT FAILURES (${this.failures.length}): ` + this.failures.join(" ;; "));
  }
}

export async function authedContext(browser: import("@playwright/test").Browser, tgId: number, theme: TelegramTheme = "light"): Promise<BrowserContext> {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, colorScheme: theme });
  const raw = buildInitData({ id: tgId, firstName: "Audit" }, BOT_TOKEN);
  await ctx.addInitScript(({ raw, theme }) => {
    (window as any).Telegram = { WebApp: { initData: raw, initDataUnsafe: {}, version: "7.0", platform: "ios", colorScheme: theme, themeParams: theme === "dark" ? { bg_color: "#17212b", text_color: "#f5f5f5", hint_color: "#708499", link_color: "#6ab3f3", button_color: "#5288c1", button_text_color: "#ffffff", secondary_bg_color: "#232e3c", section_bg_color: "#17212b", subtitle_text_color: "#708499", destructive_text_color: "#ec3942" } : {}, isVersionAtLeast: () => true, ready() {}, expand() {}, close() {}, setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {}, disableVerticalSwipes() {}, enableClosingConfirmation() {}, disableClosingConfirmation() {}, onEvent() {}, offEvent() {}, HapticFeedback: { impactOccurred() {}, notificationOccurred() {}, selectionChanged() {} } } };
  }, { raw, theme });
  await ctx.route("https://telegram.org/js/telegram-web-app.js", (r) => r.fulfill({ status: 200, contentType: "application/javascript", body: "" }));
  return ctx;
}

export const nav = (page: Page, name: string) => page.getByRole("button", { name, exact: true });

/** Real UI onboarding as a new Telegram user (AUTH + DOMAIN NECESSITY, through the UI). */
export async function onboardViaUi(T: Trace, reps = "8") {
  const p = T.page;
  await p.goto("/"); await p.waitForTimeout(2500);
  T.log("OPEN Mini App (new user)");
  await p.getByLabel("Число подтягиваний").fill(reps);
  await T.tap("Далее", p.getByRole("button", { name: "Далее" }));
  await T.tap("Да", p.getByRole("button", { name: "Да" }));
  await T.tap("Продолжить", p.getByRole("button", { name: "Продолжить" }));
  await p.getByLabel("Вес, кг").fill("78"); await T.tap("Далее", p.getByRole("button", { name: "Далее" }));
  await p.getByLabel("Рост, см").fill("180"); await T.tap("Далее", p.getByRole("button", { name: "Далее" }));
  await p.getByLabel("Пол").selectOption({ label: "Мужской" }); await T.tap("Далее", p.getByRole("button", { name: "Далее" }));
  await p.getByLabel("Дата рождения").fill("1992-04-15"); await T.tap("Далее", p.getByRole("button", { name: "Далее" }));
  await p.getByLabel("Часовой пояс").selectOption({ label: "Москва (UTC+3)" });
  await T.tap("Готово", p.getByRole("button", { name: "Готово" }));
  await p.waitForTimeout(1500);
  await T.check("Home after onboarding (UI onboarding possible)", await p.getByText("Что потренируем сегодня?").isVisible(), "UNFILED");
}
export { expect };
