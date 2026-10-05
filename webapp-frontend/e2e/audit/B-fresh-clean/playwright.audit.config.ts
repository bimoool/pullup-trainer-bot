import { defineConfig } from "@playwright/test";

// B-fresh-clean audit config. executablePath: the installed @playwright/test (1.63) expects
// chromium build 1243 but /opt/pw-browsers only ships 1194 (harness env quirk, see FINDINGS F-B-FRESH-CLEAN-ENV).
export default defineConfig({
  testDir: ".",
  testMatch: /.*\.spec\.ts$/,
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 240_000,
  outputDir: "../../../../docs/audit/wave1/B-fresh-clean/artifacts/pw",
  reporter: [["list"]],
  use: {
    baseURL: process.env.AUDIT_BASE_URL ?? "http://127.0.0.1:8091",
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
    actionTimeout: 15_000,
    trace: "on",
    screenshot: "on",
    launchOptions: { executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome" },
  },
});
