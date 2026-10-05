import { defineConfig } from "@playwright/test";

// B-fresh-catalog: baseURL = uvicorn :8092 (DB pullup_audit_d, migrations + catalogue scripts).
export default defineConfig({
  testDir: ".",
  testMatch: /.*\.spec\.ts$/,
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 120_000,
  reporter: "list",
  outputDir: "../../../../docs/audit/wave1/B-fresh-catalog/artifacts/pw-output",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:8092",
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    trace: "on",
    screenshot: "on",
    launchOptions: { executablePath: process.env.CHROME_PATH ?? "/opt/pw-browsers/chromium-1194/chrome-linux/chrome" },
  },
});
