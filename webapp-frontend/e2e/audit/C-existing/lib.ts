import type { Page, TestInfo } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
const __dirname = path.dirname(fileURLToPath(import.meta.url));
import { buildInitData } from "../../fixtures/initData";
import { mockTelegramWebApp } from "../../fixtures/telegramMock";

export const OUT = path.resolve(__dirname, "../../../../docs/audit/wave1/C-existing/artifacts");
export const BOT_TOKEN = "audit-token";

export class Log {
  lines: string[] = [];
  net: string[] = [];
  consoleErr: string[] = [];
  constructor(public name: string) {}
  t() { return new Date().toISOString().slice(11, 19); }
  add(kind: string, msg: string, flag = "") { const l = `${this.t()} ${kind} ${msg}${flag ? "   " + flag : ""}`; this.lines.push(l); console.log(l); }
  flush() {
    fs.mkdirSync(OUT, { recursive: true });
    fs.writeFileSync(path.join(OUT, `${this.name}.trace.txt`), this.lines.join("\n") + "\n\n--- NETWORK (api non-2xx and mutations) ---\n" + this.net.join("\n") + "\n\n--- CONSOLE ERRORS ---\n" + this.consoleErr.join("\n") + "\n");
  }
}

export async function open(page: Page, tg: number, log: Log, opts: { theme?: "light" | "dark" } = {}) {
  page.on("console", (m) => { if (m.type() === "error") log.consoleErr.push(m.text().slice(0, 300)); });
  page.on("dialog", async (d) => { log.add("DIALOG", `${d.type()}: ${d.message()}`); await d.accept(); });
  page.on("pageerror", (e) => log.consoleErr.push("PAGEERROR " + String(e).slice(0, 300)));
  page.on("response", async (r) => {
    const u = r.url();
    if (!u.includes("/api/")) return;
    const m = r.request().method();
    if (r.status() >= 400 || m !== "GET") {
      let body = "";
      try { body = (await r.text()).slice(0, 300); } catch {}
      log.net.push(`${log.t()} ${m} ${u.replace("http://127.0.0.1:8093", "")} -> ${r.status()} ${body}`);
    }
  });
  const raw = buildInitData({ id: tg, firstName: "Audit" }, BOT_TOKEN);
  await mockTelegramWebApp(page, raw, opts.theme ?? "light", {});
  await page.goto("/");
}

export async function shot(page: Page, log: Log, label: string) {
  fs.mkdirSync(OUT, { recursive: true });
  const f = path.join(OUT, `${log.name}__${label.replace(/[^a-zA-Z0-9_-]+/g, "_")}.png`);
  await page.screenshot({ path: f, fullPage: false });
  return f;
}

export async function body(page: Page) {
  return (await page.locator("body").innerText()).replace(/\n+/g, " | ").slice(0, 900);
}

export async function tab(page: Page, name: string) {
  await page.locator("nav, [role=tablist], body").getByText(name, { exact: true }).last().click();
  await page.waitForTimeout(1800);
}

export async function expectText(page: Page, log: Log, what: string, re: RegExp, flag: string): Promise<boolean> {
  await page.waitForTimeout(300);
  const b = await body(page);
  const ok = re.test(b);
  log.add("EXPECT", what);
  log.add("ACTUAL", b.slice(0, 400), ok ? "OK" : `FAIL ${flag}`);
  return ok;
}

/** log N sets in the Live screen as a user: Готов -> reps -> Готово (-> skip rest). Returns sets logged. */
export async function liveSets(page: Page, log: Log, n: number, reps = 10): Promise<number> {
  let done = 0;
  for (let i = 0; i < n; i++) {
    const ready = page.getByRole("button", { name: "Готов", exact: true });
    try { await ready.click({ timeout: 8000 }); } catch { /* may already be in ПОШЁЛ */ }
    const field = page.getByLabel("Повторений");
    try { await field.fill(String(reps), { timeout: 8000 }); } catch { log.add("LIVE", "no reps field on set " + (i + 1) + " :: " + await body(page), "FAIL?"); break; }
    await page.getByRole("button", { name: "Готово", exact: true }).click();
    await page.waitForTimeout(800);
    log.add("LIVE", `set ${i + 1} logged (${reps}) :: ` + (await body(page)).slice(0, 220));
    done++;
    const skip = page.getByRole("button", { name: "Пропустить отдых" });
    if (i < n - 1) { try { await skip.click({ timeout: 4000 }); } catch {} }
  }
  return done;
}
