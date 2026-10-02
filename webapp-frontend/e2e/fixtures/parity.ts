import { expect, type Locator, type Page } from "@playwright/test";

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

// --- Generic helpers added by the Full sweep (#277); additive, nothing above changed. ----------

export const THEMES = ["light", "dark"] as const;
export type Theme = (typeof THEMES)[number];

/** Every width × theme combination, in a fixed order (index = per-combination seed offset). */
export const COMBOS = WIDTHS.flatMap((width) => THEMES.map((theme) => ({ width, theme })));

/**
 * The screen is usable: no horizontal overflow (document.scrollingElement vs. the viewport) and not
 * blank — besides the greeting header and the bottom tab bar there is real content on it.
 */
export async function expectScreenHealthy(page: Page, where: string, minChars = 40) {
  const { scrollWidth, innerWidth, contentChars } = await page.evaluate(() => {
    const scroller = document.scrollingElement ?? document.documentElement;
    const tabbarChars = (document.querySelector(".bottom-tabbar") as HTMLElement | null)?.innerText.length ?? 0;
    return {
      scrollWidth: scroller.scrollWidth,
      innerWidth: window.innerWidth,
      contentChars: document.body.innerText.trim().length - tabbarChars,
    };
  });
  expect(scrollWidth, `горизонтальный overflow на «${where}»`).toBeLessThanOrEqual(innerWidth);
  expect(contentChars, `пустой экран «${where}»`).toBeGreaterThan(minChars);
}

type CapturedDownloads = { downloads: { url: string; file_name: string }[]; opened: string[] };

/**
 * Call BEFORE openAppAs. Records Telegram `WebApp.downloadFile(...)` calls and `window.open(...)`
 * (the non-Telegram fallback) instead of really downloading; `read()` returns what was captured.
 */
export async function captureDownloads(page: Page): Promise<{ read: () => Promise<CapturedDownloads> }> {
  await page.addInitScript(() => {
    const captured = { downloads: [] as { url: string; file_name: string }[], opened: [] as string[] };
    (window as unknown as { __captured: unknown }).__captured = captured;
    let telegram: unknown;
    Object.defineProperty(window, "Telegram", {
      configurable: true,
      get: () => telegram,
      set: (value: { WebApp: Record<string, unknown> }) => {
        value.WebApp.downloadFile = (params: { url: string; file_name: string }) => captured.downloads.push(params);
        telegram = value;
      },
    });
    window.open = (url) => {
      captured.opened.push(String(url));
      return null;
    };
  });
  return { read: () => page.evaluate(() => (window as unknown as { __captured: CapturedDownloads }).__captured) };
}

/**
 * Журнал v2 (#280): тап по карточке открывает шторку действий; этот хелпер тапает карточку и выбирает
 * действие шторки (по умолчанию «Открыть» — прежний экран деталей).
 */
export async function openJournalEntry(
  page: Page, card: Locator, action: "open" | "edit" | "clone" | "workout" | "delete" = "open",
) {
  await card.click();
  await expect(page.getByTestId("journal-entry-sheet")).toBeVisible();
  await page.getByTestId(`journal-sheet-${action}`).click();
}

/** Аналитика: метрика — выпадающий список (нативный select) в единой шапке, #286. */
export const metricSelect = (page: Page) => page.getByRole("combobox", { name: "Метрика" });
export async function selectMetric(page: Page, label: "Тренировки" | "Минуты") {
  await metricSelect(page).selectOption({ label });
  await expect(metricSelect(page).locator("option:checked")).toHaveText(label);
}
