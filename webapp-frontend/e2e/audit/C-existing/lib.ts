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
