import { expect, test as base, type Page, type TestInfo } from "@playwright/test";

import { buildInitData, launchUrl, QA_IDENTITIES, stagingBotToken, type QaIdentity } from "./initData";

export type ApiEntry = { t: string; method: string; path: string; status: number };

export interface QaSession {
  page: Page;
  identity: QaIdentity;
  consoleErrors: string[];
  apiLog: ApiEntry[];
  /** Latest captured JSON body of GET /api/v2/plan (what the UI itself received). */
  lastPlanJson: () => unknown;
  /** Re-open the app the way Telegram does (fresh launch URL), e.g. after a long pause. */
  relaunch: () => Promise<void>;
  /** Fail on 5xx, on unexpected 4xx and on real console errors. */
  assertClean: (opts?: { allowedStatuses?: number[] }) => void;
}

// Headless browsers have no Wake Lock; the Telegram SDK logs init() noise outside a native client.
// "Failed to load resource": favicon / third-party script blocked; real /api failures are caught via apiLog.
const NOISE = ["Wake Lock", "Telegram SDK init() failed", "Failed to load resource", "BackButton toggle failed"];

async function openAs(page: Page, identity: QaIdentity, baseURL: string, testInfo: TestInfo): Promise<QaSession> {
  const consoleErrors: string[] = [];
  const apiLog: ApiEntry[] = [];
  let planJson: unknown = null;

  page.on("console", (m) => {
    if (m.type() === "error" && !NOISE.some((n) => m.text().includes(n))) consoleErrors.push(m.text());
  });
  page.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`));
  page.on("response", async (r) => {
    const url = new URL(r.url());
    if (!url.pathname.startsWith("/api/")) return;
    apiLog.push({ t: new Date().toISOString(), method: r.request().method(), path: url.pathname + url.search, status: r.status() });
    if (r.request().method() === "GET" && url.pathname === "/api/v2/plan" && r.ok()) {
      try {
        planJson = await r.json();
      } catch {
        /* body not available (navigation) — keep the previous capture */
      }
    }
  });

  const launch = async () => {
    const initData = buildInitData(QA_IDENTITIES[identity], stagingBotToken());
    await page.goto(launchUrl(baseURL, initData));
    // Onboarded identity: bottom navigation is the first stable landmark of a loaded app.
    await expect(page.locator(".bottom-tabbar")).toBeVisible({ timeout: 45_000 });
  };
  await launch();

  return {
    page, identity, consoleErrors, apiLog,
    lastPlanJson: () => planJson,
    relaunch: launch,
    assertClean: (opts = {}) => {
      const allowed = opts.allowedStatuses ?? [];
      const bad = apiLog.filter((e) => e.status >= 500 || (e.status >= 400 && !allowed.includes(e.status)));
      expect(bad, `unexpected /api failures: ${JSON.stringify(bad)}`).toEqual([]);
      expect(consoleErrors, "console errors").toEqual([]);
    },
  };
}

export const test = base.extend<{ qa: (identity: QaIdentity) => Promise<QaSession> }>({
  qa: async ({ page, baseURL }, use, testInfo) => {
    const sessions: QaSession[] = [];
    await use(async (identity) => {
      const s = await openAs(page, identity, baseURL!, testInfo);
      sessions.push(s);
      return s;
    });
    // Always attach evidence (pass or fail); never contains the token or initData (headers are not logged).
    for (const s of sessions) {
      await testInfo.attach(`api-log-${s.identity}.json`, { body: JSON.stringify(s.apiLog, null, 2), contentType: "application/json" });
      await testInfo.attach(`console-errors-${s.identity}.json`, { body: JSON.stringify(s.consoleErrors, null, 2), contentType: "application/json" });
      const plan = s.lastPlanJson();
      if (plan !== null) {
        await testInfo.attach(`api-v2-plan-${s.identity}.json`, { body: JSON.stringify(plan, null, 2), contentType: "application/json" });
      }
    }
  },
});

export { expect };

export const nav = (page: Page, name: string) => page.getByRole("button", { name, exact: true });

/** Click + wait for the server's 200 (the app deliberately drops a second tap while a request is in flight). */
export async function clickAndSync(page: Page, name: string, urlPart: string) {
  const response = page.waitForResponse((r) => r.url().includes(urlPart) && r.status() === 200);
  await page.getByRole("button", { name, exact: true }).click();
  await response;
}

/** One block of reps/max sets with rest skipped (same flow as e2e/fixtures/builderFlow.ts::playSets). */
export async function playSets(page: Page, values: string[]) {
  for (let i = 0; i < values.length; i += 1) {
    await clickAndSync(page, "Готов", "/phase/next");
    await expect(page.getByText("Пошёл")).toBeVisible();
    await page.getByLabel(/Результат|Секунды|Повторений/).fill(values[i]);
    await clickAndSync(page, "Готово", "/sets:batch");
    if (i < values.length - 1) {
      await clickAndSync(page, "Пропустить отдых", "/phase/next");
    }
  }
}

/** Pre-screen «Начать» -> live screen. */
export async function confirmPreScreen(page: Page) {
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await expect(page.getByText("Живая тренировка")).toBeVisible();
}

export async function finishAndSave(page: Page) {
  await page.getByRole("button", { name: "Завершить", exact: true }).first().click();
  await clickAndSync(page, "Сохранить и завершить", "/complete");
  await expect(page.getByText("Тренировка завершена")).toBeVisible();
}
