import { execFileSync } from "node:child_process";
import { defineConfig, devices } from "@playwright/test";

// Same guard as the pre-migration step. No configurable remote base URL.
execFileSync(process.env.SMOKE_PYTHON ?? "python", ["../../scripts/isolated_smoke_guard.py"], { stdio: "pipe" });

export default defineConfig({
  testDir: "./smoke",
  testMatch: "isolated.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [["./smoke/statusReporter.ts"]],
  outputDir: "/tmp/pullup-smoke-playwright",
  use: {
    baseURL: "http://127.0.0.1:8001",
    trace: "off",
    screenshot: "off",
    video: "off",
    locale: "ru-RU",
    timezoneId: "Europe/Moscow",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  projects: [{
    name: "chromium-mobile",
    use: {
      ...devices["Pixel 7"],
      launchOptions: process.env.E2E_CHROMIUM_PATH ? { executablePath: process.env.E2E_CHROMIUM_PATH } : {},
    },
  }],
});
