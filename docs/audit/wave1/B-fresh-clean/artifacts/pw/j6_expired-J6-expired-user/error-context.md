# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: j6_expired.spec.ts >> J6 expired user
- Location: audit/B-fresh-clean/j6_expired.spec.ts:8:1

# Error details

```
Error: AUDIT FAILURES (6): F-B-FRESH-CLEAN-08 (stale subscription cache label): Subscription screen says expired (not 'пробный период') right after expiry ;; F-B-FRESH-CLEAN-05 (paywall): Subscription screen offers a way to pay ;; F-B-FRESH-CLEAN-05: Главная: paywall / no_access explanation visible for expired user ;; F-B-FRESH-CLEAN-05: Планы: paywall / no_access explanation visible for expired user ;; F-B-FRESH-CLEAN-05: Журнал: paywall / no_access explanation visible for expired user ;; F-B-FRESH-CLEAN-05: Аналитика: paywall / no_access explanation visible for expired user
```

# Page snapshot

```yaml
- generic [ref=f6e4]:
  - paragraph [ref=f6e5]: Привет, Audit!
  - generic [ref=f6e6]:
    - paragraph [ref=f6e7]: Новая тренировка
    - generic [ref=f6e8]:
      - generic [ref=f6e9]: Название
      - textbox "Название" [ref=f6e10]:
        - /placeholder: Например, 3 минуты подтягиваний
    - paragraph [ref=f6e11]: Сначала название. Упражнения, подходы и отдых вы настроите на следующем шаге.
    - button "Создать и добавить упражнения" [disabled] [ref=f6e12]
```

# Test source

```ts
  1  | import { expect, type BrowserContext, type Page, type TestInfo } from "@playwright/test";
  2  | import fs from "node:fs";
  3  | import path from "node:path";
  4  | import { buildInitData } from "../../fixtures/initData";
  5  | type TelegramTheme = "light" | "dark";
  6  | 
  7  | export const BOT_TOKEN = "audit-token";
  8  | export const ART = "/home/user/pullup-trainer-bot/docs/audit/wave1/B-fresh-clean/artifacts";
  9  | 
  10 | export class Trace {
  11 |   failures: string[] = [];
  12 |   lines: string[] = [];
  13 |   constructor(public name: string, public page: Page, private info: TestInfo) {
  14 |     page.on("response", async (r) => {
  15 |       if (r.url().includes("/api/") && r.status() >= 400) {
  16 |         let b = ""; try { b = (await r.text()).slice(0, 300); } catch { /* ignore */ }
  17 |         this.log(`NETFAIL ${r.status()} ${r.request().method()} ${new URL(r.url()).pathname} :: ${b}`);
  18 |       }
  19 |     });
  20 |     page.on("pageerror", (e) => this.log(`PAGEERROR ${e.message.slice(0, 200)}`));
  21 |     page.on("console", (m) => { if (m.type() === "error" && !/Telegram SDK init/.test(m.text())) this.log(`CONSOLE.error ${m.text().slice(0, 200)}`); });
  22 |   }
  23 |   log(s: string) {
  24 |     const t = new Date().toISOString().slice(11, 19);
  25 |     const line = `${t} ${s}`;
  26 |     this.lines.push(line);
  27 |     fs.mkdirSync(ART, { recursive: true });
  28 |     fs.appendFileSync(path.join(ART, `trace-${this.name}.log`), line + "\n");
  29 |   }
  30 |   async visible(): Promise<string> {
  31 |     return (await this.page.locator("body").innerText()).replace(/\s*\n+\s*/g, " | ").slice(0, 700);
  32 |   }
  33 |   async shot(label: string) { await this.page.screenshot({ path: path.join(ART, `${this.name}-${label}.png`) }); }
  34 |   async open(label: string) { this.log(`OPEN ${label}`); }
  35 |   async tap(label: string, loc: ReturnType<Page["locator"]>) { this.log(`TAP "${label}"`); await loc.first().click(); await this.page.waitForTimeout(900); }
  36 |   async reload(label = "") {
  37 |     this.log(`RELOAD ${label}`); await this.page.reload(); await this.page.waitForTimeout(2200);
  38 |   }
  39 |   /** EXPECT/ACTUAL pair. ok decides; findingId is cited on FAIL. Never throws: the run continues, failure is collected. */
  40 |   async check(expectText: string, ok: boolean, findingId: string, shotLabel?: string) {
  41 |     const actual = await this.visible();
  42 |     this.log(`EXPECT ${expectText}`);
  43 |     this.log(`ACTUAL ${actual}   ${ok ? "OK" : "FAIL " + findingId}`);
  44 |     if (!ok) { this.failures.push(`${findingId}: ${expectText}`); if (shotLabel) await this.shot(shotLabel); }
  45 |     else if (shotLabel) await this.shot(shotLabel);
  46 |     return ok;
  47 |   }
  48 |   finish() {
  49 |     this.log(`SUMMARY ${this.failures.length ? "FAIL " + JSON.stringify(this.failures) : "PASS"}`);
  50 |     this.info.annotations.push({ type: "audit-failures", description: JSON.stringify(this.failures) });
> 51 |     if (this.failures.length) throw new Error(`AUDIT FAILURES (${this.failures.length}): ` + this.failures.join(" ;; "));
     |                                     ^ Error: AUDIT FAILURES (6): F-B-FRESH-CLEAN-08 (stale subscription cache label): Subscription screen says expired (not 'пробный период') right after expiry ;; F-B-FRESH-CLEAN-05 (paywall): Subscription screen offers a way to pay ;; F-B-FRESH-CLEAN-05: Главная: paywall / no_access explanation visible for expired user ;; F-B-FRESH-CLEAN-05: Планы: paywall / no_access explanation visible for expired user ;; F-B-FRESH-CLEAN-05: Журнал: paywall / no_access explanation visible for expired user ;; F-B-FRESH-CLEAN-05: Аналитика: paywall / no_access explanation visible for expired user
  52 |   }
  53 | }
  54 | 
  55 | export async function authedContext(browser: import("@playwright/test").Browser, tgId: number, theme: TelegramTheme = "light"): Promise<BrowserContext> {
  56 |   const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, colorScheme: theme });
  57 |   const raw = buildInitData({ id: tgId, firstName: "Audit" }, BOT_TOKEN);
  58 |   await ctx.addInitScript(({ raw, theme }) => {
  59 |     (window as any).Telegram = { WebApp: { initData: raw, initDataUnsafe: {}, version: "7.0", platform: "ios", colorScheme: theme, themeParams: theme === "dark" ? { bg_color: "#17212b", text_color: "#f5f5f5", hint_color: "#708499", link_color: "#6ab3f3", button_color: "#5288c1", button_text_color: "#ffffff", secondary_bg_color: "#232e3c", section_bg_color: "#17212b", subtitle_text_color: "#708499", destructive_text_color: "#ec3942" } : {}, isVersionAtLeast: () => true, ready() {}, expand() {}, close() {}, setHeaderColor() {}, setBackgroundColor() {}, setBottomBarColor() {}, disableVerticalSwipes() {}, enableClosingConfirmation() {}, disableClosingConfirmation() {}, onEvent() {}, offEvent() {}, HapticFeedback: { impactOccurred() {}, notificationOccurred() {}, selectionChanged() {} } } };
  60 |   }, { raw, theme });
  61 |   await ctx.route("https://telegram.org/js/telegram-web-app.js", (r) => r.fulfill({ status: 200, contentType: "application/javascript", body: "" }));
  62 |   return ctx;
  63 | }
  64 | 
  65 | export const nav = (page: Page, name: string) => page.getByRole("button", { name, exact: true });
  66 | 
  67 | /** Real UI onboarding as a new Telegram user (AUTH + DOMAIN NECESSITY, through the UI). */
  68 | export async function onboardViaUi(T: Trace, reps = "8") {
  69 |   const p = T.page;
  70 |   await p.goto("/"); await p.waitForTimeout(2500);
  71 |   T.log("OPEN Mini App (new user)");
  72 |   await p.getByLabel("Число подтягиваний").fill(reps);
  73 |   await T.tap("Далее", p.getByRole("button", { name: "Далее" }));
  74 |   await T.tap("Да", p.getByRole("button", { name: "Да" }));
  75 |   await T.tap("Продолжить", p.getByRole("button", { name: "Продолжить" }));
  76 |   await p.getByLabel("Вес, кг").fill("78"); await T.tap("Далее", p.getByRole("button", { name: "Далее" }));
  77 |   await p.getByLabel("Рост, см").fill("180"); await T.tap("Далее", p.getByRole("button", { name: "Далее" }));
  78 |   await p.getByLabel("Пол").selectOption({ label: "Мужской" }); await T.tap("Далее", p.getByRole("button", { name: "Далее" }));
  79 |   await p.getByLabel("Дата рождения").fill("1992-04-15"); await T.tap("Далее", p.getByRole("button", { name: "Далее" }));
  80 |   await p.getByLabel("Часовой пояс").selectOption({ label: "Москва (UTC+3)" });
  81 |   await T.tap("Готово", p.getByRole("button", { name: "Готово" }));
  82 |   await p.waitForTimeout(1500);
  83 |   await T.check("Home after onboarding (UI onboarding possible)", await p.getByText("Что потренируем сегодня?").isVisible(), "UNFILED");
  84 | }
  85 | export { expect };
  86 | 
  87 | /** Telegram id inside this role's 7100001-7100099 range; AUDIT_UID_OFFSET lets a re-run use fresh users on the same DB. */
  88 | export const uid = (n: number) => 7100000 + Number(process.env.AUDIT_UID_OFFSET ?? 0) + n;
  89 | 
```