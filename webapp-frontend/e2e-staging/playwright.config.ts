import { defineConfig, devices } from "@playwright/test";

/**
 * Journeys against the REAL deployed staging, not a local copy (docs/STAGING_QA_HARNESS.md).
 *
 *   STAGING_URL        https://staging.app.bimoool.com   (required; no default on purpose)
 *   STAGING_BOT_TOKEN  staging bot token, from GitHub secret / server env — used only to sign initData
 *   STAGING_PROJECT    comma list of projects to run (default: iphone-webkit,chromium-mobile)
 *   E2E_CHROMIUM_PATH  optional chromium binary override (sandboxes with a pre-installed browser)
 *
 * No webServer: nothing is started here. The deployment under test must already be up.
 */
const BASE_URL = process.env.STAGING_URL?.replace(/\/+$/, "");
if (!BASE_URL) {
  throw new Error("STAGING_URL is not set (e.g. https://staging.app.bimoool.com) — this suite never targets localhost by default");
}

const chromiumPath = process.env.E2E_CHROMIUM_PATH;
const chromiumLaunch = chromiumPath ? { launchOptions: { executablePath: chromiumPath } } : {};

const ALL_PROJECTS = [
  // iPhone Safari engine: the owner's failing device class. WebKit emulation is not a real device,
  // the release rule still requires the owner's device check.
  { name: "iphone-webkit", use: { ...devices["iPhone 14"] } },
  { name: "chromium-mobile", use: { ...devices["Pixel 7"], ...chromiumLaunch } },
];
const wanted = (process.env.STAGING_PROJECT ?? "iphone-webkit,chromium-mobile").split(",").map((s) => s.trim());

export default defineConfig({
  testDir: "./specs",
  // The journeys share ONE mutable identity (qa_fresh_active) and are ordered by file name.
  fullyParallel: false,
  workers: 1,
  retries: 0, // a retry could mask a state-dependent defect; the identity is reset by reprovisioning, not by retrying
  forbidOnly: !!process.env.CI,
  timeout: 180_000,
  expect: { timeout: 15_000 },
  outputDir: "test-results",
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }], ["json", { outputFile: "test-results/results.json" }]],
  use: {
    baseURL: BASE_URL,
    trace: "on",
    screenshot: "on",
    video: "retain-on-failure",
    actionTimeout: 15_000,
    navigationTimeout: 45_000,
    locale: "ru-RU",
    timezoneId: "Europe/Moscow",
  },
  projects: ALL_PROJECTS.filter((p) => wanted.includes(p.name)),
});
