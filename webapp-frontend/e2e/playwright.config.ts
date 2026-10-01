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

const MOBILE_SPEC = /mobile-layout\.spec\.ts$/;
const MOBILE_WIDTHS = [320, 375, 390];
// Экранная клавиатура в редакторе тренировки (issue #250): только 320 и 390.
const KEYBOARD_SPEC = /keyboard-viewport\.spec\.ts$/;
const KEYBOARD_WIDTHS = [320, 390];

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
  projects: [
    { name: "chromium", testIgnore: [MOBILE_SPEC, KEYBOARD_SPEC], use: { ...devices["Desktop Chrome"] } },
    // Узкий набор критичных мобильных проверок (issue #244): только
    // mobile-layout.spec.ts, а не весь десктопный набор на каждой ширине.
    ...MOBILE_WIDTHS.map((width) => ({
      name: `mobile-${width}`,
      testMatch: MOBILE_SPEC,
      use: { ...devices["Pixel 5"], viewport: { width, height: 740 } },
    })),
    ...KEYBOARD_WIDTHS.map((width) => ({
      name: `keyboard-${width}`,
      testMatch: KEYBOARD_SPEC,
      use: { ...devices["Pixel 5"], viewport: { width, height: 740 } },
    })),
  ],
});
