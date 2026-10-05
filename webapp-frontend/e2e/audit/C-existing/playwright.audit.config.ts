import { defineConfig, devices } from "@playwright/test";
import * as path from "node:path";
import { fileURLToPath } from "node:url";
const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  testDir: __dirname,
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 180_000,
  reporter: "list",
  outputDir: path.resolve(__dirname, "../../../../docs/audit/wave1/C-existing/artifacts/pw"),
  use: {
    baseURL: "http://127.0.0.1:8093",
    trace: "on",
    actionTimeout: 10_000,
    screenshot: "on",
    ...devices["iPhone 13"],
    viewport: { width: 390, height: 844 },
    colorScheme: "light",
  },
  projects: [{ name: "chromium-390", use: { browserName: "chromium", launchOptions: { executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome" } } }],
});
