# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: j6.spec.ts >> J6 audit_trial can train
- Location: audit/C-existing/j6.spec.ts:17:3

# Error details

```
TimeoutError: locator.click: Timeout 10000ms exceeded.
Call log:
  - waiting for getByRole('button', { name: 'Начать' }).last()

```

# Page snapshot

```yaml
- generic [ref=e5]:
  - banner [ref=e6]:
    - paragraph [ref=e7]: Тренировка
    - paragraph [ref=e8]: Подтягивания
  - paragraph [ref=e9]: Ещё рано для следующей тренировки — минимальный отдых между тренировками не прошёл.
  - button "Перейти в обычную \"Тренировку\"" [ref=e11] [cursor=pointer]
```

# Test source

```ts
  1   | import type { Page, TestInfo } from "@playwright/test";
  2   | import * as fs from "node:fs";
  3   | import * as path from "node:path";
  4   | import { fileURLToPath } from "node:url";
  5   | const __dirname = path.dirname(fileURLToPath(import.meta.url));
  6   | import { buildInitData } from "../../fixtures/initData";
  7   | import { mockTelegramWebApp } from "../../fixtures/telegramMock";
  8   | 
  9   | export const OUT = path.resolve(__dirname, "../../../../docs/audit/wave1/C-existing/artifacts");
  10  | export const BOT_TOKEN = "audit-token";
  11  | 
  12  | export class Log {
  13  |   lines: string[] = [];
  14  |   net: string[] = [];
  15  |   consoleErr: string[] = [];
  16  |   constructor(public name: string) {}
  17  |   t() { return new Date().toISOString().slice(11, 19); }
  18  |   add(kind: string, msg: string, flag = "") { const l = `${this.t()} ${kind} ${msg}${flag ? "   " + flag : ""}`; this.lines.push(l); console.log(l); }
  19  |   flush() {
  20  |     fs.mkdirSync(OUT, { recursive: true });
  21  |     fs.writeFileSync(path.join(OUT, `${this.name}.trace.txt`), this.lines.join("\n") + "\n\n--- NETWORK (api non-2xx and mutations) ---\n" + this.net.join("\n") + "\n\n--- CONSOLE ERRORS ---\n" + this.consoleErr.join("\n") + "\n");
  22  |   }
  23  | }
  24  | 
  25  | export async function open(page: Page, tg: number, log: Log, opts: { theme?: "light" | "dark" } = {}) {
  26  |   page.on("console", (m) => { if (m.type() === "error") log.consoleErr.push(m.text().slice(0, 300)); });
  27  |   page.on("dialog", async (d) => { log.add("DIALOG", `${d.type()}: ${d.message()}`); await d.accept(); });
  28  |   page.on("pageerror", (e) => log.consoleErr.push("PAGEERROR " + String(e).slice(0, 300)));
  29  |   page.on("response", async (r) => {
  30  |     const u = r.url();
  31  |     if (!u.includes("/api/")) return;
  32  |     const m = r.request().method();
  33  |     if (r.status() >= 400 || m !== "GET") {
  34  |       let body = "";
  35  |       try { body = (await r.text()).slice(0, 300); } catch {}
  36  |       log.net.push(`${log.t()} ${m} ${u.replace("http://127.0.0.1:8093", "")} -> ${r.status()} ${body}`);
  37  |     }
  38  |   });
  39  |   const raw = buildInitData({ id: tg, firstName: "Audit" }, BOT_TOKEN);
  40  |   await mockTelegramWebApp(page, raw, opts.theme ?? "light", {});
  41  |   await page.goto("/");
  42  | }
  43  | 
  44  | export async function shot(page: Page, log: Log, label: string) {
  45  |   fs.mkdirSync(OUT, { recursive: true });
  46  |   const f = path.join(OUT, `${log.name}__${label.replace(/[^a-zA-Z0-9_-]+/g, "_")}.png`);
  47  |   await page.screenshot({ path: f, fullPage: false });
  48  |   return f;
  49  | }
  50  | 
  51  | export async function body(page: Page) {
  52  |   return (await page.locator("body").innerText()).replace(/\n+/g, " | ").slice(0, 900);
  53  | }
  54  | 
  55  | export async function tab(page: Page, name: string) {
  56  |   await page.locator("nav, [role=tablist], body").getByText(name, { exact: true }).last().click();
  57  |   await page.waitForTimeout(1800);
  58  | }
  59  | 
  60  | export async function expectText(page: Page, log: Log, what: string, re: RegExp, flag: string): Promise<boolean> {
  61  |   await page.waitForTimeout(300);
  62  |   const b = await body(page);
  63  |   const ok = re.test(b);
  64  |   log.add("EXPECT", what);
  65  |   log.add("ACTUAL", b.slice(0, 400), ok ? "OK" : `FAIL ${flag}`);
  66  |   return ok;
  67  | }
  68  | 
  69  | /** log N sets in the Live screen as a user: Готов -> reps -> Готово (-> skip rest). Returns sets logged. */
  70  | export async function liveSets(page: Page, log: Log, n: number, reps = 10): Promise<number> {
  71  |   let done = 0;
  72  |   for (let i = 0; i < n; i++) {
  73  |     const ready = page.getByRole("button", { name: "Готов", exact: true });
  74  |     try { await ready.click({ timeout: 8000 }); } catch { /* may already be in ПОШЁЛ */ }
  75  |     const field = page.getByLabel("Повторений");
  76  |     try { await field.fill(String(reps), { timeout: 8000 }); } catch { log.add("LIVE", "no reps field on set " + (i + 1) + " :: " + await body(page), "FAIL?"); break; }
  77  |     await page.getByRole("button", { name: "Готово", exact: true }).click();
  78  |     await page.waitForTimeout(800);
  79  |     log.add("LIVE", `set ${i + 1} logged (${reps}) :: ` + (await body(page)).slice(0, 220));
  80  |     done++;
  81  |     const skip = page.getByRole("button", { name: "Пропустить отдых" });
  82  |     if (i < n - 1) { try { await skip.click({ timeout: 4000 }); } catch {} }
  83  |   }
  84  |   return done;
  85  | }
  86  | 
  87  | /** Plans -> Начать -> pre-screen -> Начать -> Live -> n sets -> Завершить -> rate 3 -> save. Logs ready-vs-live target. */
  88  | export async function trainOnce(page: Page, log: Log, sets = 2): Promise<{ ok: boolean; pre: string; live: string }> {
  89  |   await tab(page, "Планы");
  90  |   const plansBody = await body(page);
  91  |   log.add("VISIBLE", "Планы :: " + plansBody.slice(0, 420));
  92  |   const start = page.getByRole("button", { name: "Начать" });
  93  |   if (!(await start.count())) { log.add("ACTUAL", "no Начать button", "FAIL no-start"); return { ok: false, pre: "", live: "" }; }
  94  |   await start.first().click();
  95  |   await page.waitForTimeout(2500);
  96  |   const pre = await body(page);
  97  |   log.add("VISIBLE", "pre-screen :: " + pre);
> 98  |   await page.getByRole("button", { name: "Начать" }).last().click();
      |                                                             ^ TimeoutError: locator.click: Timeout 10000ms exceeded.
  99  |   await page.waitForTimeout(3500);
  100 |   const live = await body(page);
  101 |   log.add("VISIBLE", "live :: " + live.slice(0, 260));
  102 |   const preTarget = pre.match(/Цель 1: (\d+)/)?.[1]; const liveTarget = live.match(/Цель: (\d+)/)?.[1];
  103 |   log.add("EXPECT", "pre-screen target == live target");
  104 |   log.add("ACTUAL", `pre=${preTarget} live=${liveTarget}`, preTarget === liveTarget ? "OK" : "FAIL F-C-03 target mismatch pre-screen vs live");
  105 |   if (!/ЖИВАЯ ТРЕНИРОВКА/.test(live)) return { ok: false, pre, live };
  106 |   await liveSets(page, log, sets, 10);
  107 |   await page.getByRole("button", { name: "Завершить" }).click();
  108 |   await page.waitForTimeout(1000);
  109 |   await page.getByRole("button", { name: /^3/ }).click();
  110 |   await page.getByRole("button", { name: "Сохранить и завершить" }).click();
  111 |   await page.waitForTimeout(2500);
  112 |   log.add("VISIBLE", "summary :: " + (await body(page)).slice(0, 260));
  113 |   return { ok: /Тренировка завершена/.test(await body(page)), pre, live };
  114 | }
  115 | 
```