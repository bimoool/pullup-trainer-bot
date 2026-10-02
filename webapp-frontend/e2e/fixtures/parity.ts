import { expect, type Page } from "@playwright/test";

// Shared helpers for the Crimpd parity suite (docs/CRIMPD_FULL_PARITY_8_5.md).
// Each parity task adds its OWN file `scenarios/parity/<area>.spec.ts` (run serially by the
// `parity` project in playwright.config.ts) instead of appending to crimpd-parity.spec.ts —
// appends to one shared file made stale worker branches conflict on its tail.

/** Representative mobile widths for parity checks. */
export const WIDTHS = [320, 390] as const;

/** Read-only seeded user (`scripts/e2e_seed.py ready 900003`). */
export const READY_USER = 900_003;

export async function expectNoHorizontalOverflow(page: Page, where: string) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth, `горизонтальный overflow на «${where}»`).toBeLessThanOrEqual(clientWidth);
}

export async function openTab(page: Page, label: string) {
  await page.locator(".bottom-tabbar").getByRole("button", { name: label }).click();
}
