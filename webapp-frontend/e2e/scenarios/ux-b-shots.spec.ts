import { test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { mockPlanContract } from "../fixtures/contractMock";
import { openAppAs } from "../fixtures/setup";

// Скриншоты исполнителя B (docs/audit/ux-ref-20261018/checkpoints/B-shots). Только по явному запросу:
//   UX_B_SHOTS=1 npx playwright test scenarios/ux-b-shots.spec.ts --project=chromium
// Сид: ux_b_legacy 940204 (только чтение).
const OUT = fileURLToPath(new URL("../../../docs/audit/ux-ref-20261018/checkpoints/B-shots/", import.meta.url));
const SCHEDULE = { sessions_per_week: 3, source: "catalogue" as const, is_legacy: true, min_days_between_starts: 3, weekly_capacity: 2 };

test.skip(process.env.UX_B_SHOTS !== "1", "скриншоты — только по запросу");

for (const [label, width, theme] of [["light-390", 390, "light"], ["dark-390", 390, "dark"], ["light-320", 320, "light"]] as const) {
  test(`plans ${label}`, async ({ page }) => {
    mkdirSync(OUT, { recursive: true });
    await page.setViewportSize({ width, height: 900 });
    await mockPlanContract(page, { schedule: SCHEDULE });
    await openAppAs(page, 940_204, { theme });
    await page.getByRole("button", { name: "Планы" }).click();
    await page.getByTestId("plans-now-card").waitFor();
    await page.waitForTimeout(600);
    await page.screenshot({ path: `${OUT}plans-legacy-${label}.png`, fullPage: true });

    await page.getByTestId("elective-open").click();
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${OUT}elective-${label}.png` });
    await page.unrouteAll({ behavior: "ignoreErrors" });
  });
}

test("program detail after add + home plus sheet (light-390)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 900 });
  await mockPlanContract(page);
  await openAppAs(page, 940_201);
  await page.locator(".program-card-button").first().click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await page.getByTestId("program-open-plan").waitFor();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}program-detail-after-add-light-390.png`, fullPage: true });
  await page.unrouteAll({ behavior: "ignoreErrors" });
});
