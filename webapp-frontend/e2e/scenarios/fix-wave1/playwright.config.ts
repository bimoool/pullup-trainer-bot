import { defineConfig } from "@playwright/test";

// Own config for the fix-wave1 journeys: one worker, mobile viewport, optional chromium path
// (E2E_CHROMIUM_PATH, for machines whose installed Playwright expects another chromium build).
export default defineConfig({
  testDir: ".",
  testMatch: /.*\.spec\.ts$/,
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 180_000,
  reporter: [["list"]],
  outputDir: process.env.E2E_OUTPUT_DIR ?? "./.artifacts",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8001",
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    actionTimeout: 15_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: process.env.E2E_CHROMIUM_PATH ? { executablePath: process.env.E2E_CHROMIUM_PATH } : {},
  },
});
