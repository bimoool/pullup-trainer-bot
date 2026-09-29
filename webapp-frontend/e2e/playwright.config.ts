import { defineConfig, devices } from "@playwright/test";

/**
 * baseURL — уже поднятый app/web/main.py (uvicorn), отдающий и /api/*, и
 * собранную статику webapp-frontend/dist одним origin'ом (см. docs/mini-app.md,
 * "Mini App: Этап 0"), тот же процесс, что реально работает в проде под
 * Dockerfile.web. Набор НЕ поднимает сервер сам (webServer в конфиге
 * Playwright) — CI явно стартует uvicorn заранее и ждёт /health, чтобы тот
 * же шаг мог сначала прогнать scripts/e2e_seed.py против той же БД (см.
 * webapp-frontend/e2e/README.md).
 */
const BASE_URL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:8001";

export default defineConfig({
  testDir: "./scenarios",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["html", { open: "never" }], ["list"]] : "list",
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
