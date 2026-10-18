import { expect, type Page, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

/**
 * Аудит staging 6475bc0: в «Свободном пуле» подпись состояния занятия («Не уместится на этой неделе», «Доступно с …»)
 * не сжималась (nowrap, flex: 0 0 auto) и заезжала под «Начать», а название сжималось до «…». Состояния подставлены
 * в ответ /api/v2/plan (правила плана не трогаем — проверяется только вёрстка строки). Сид: plan_week_start_session
 * 900016 (только чтение). 320 и 375 px.
 */
test.setTimeout(60_000);

async function withOccurrenceStates(page: Page) {
  await page.route("**/api/v2/plan", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    const course = (body.plan.plan_items as Array<Record<string, unknown>>)
      .filter((item) => item.program_inclusion_id !== null && item.occurrence_index != null);
    if (course[0]) {
      Object.assign(course[0], { state: "too_early", blocked_reason: "too_early", start_allowed: false, available_from: "2026-12-17" });
    }
    if (course[1]) {
      Object.assign(course[1], { state: "infeasible", blocked_reason: "infeasible", start_allowed: false });
    }
    await route.fulfill({ response, json: body });
  });
}

const intersects = (a: DOMRect, b: DOMRect) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;

for (const width of [320, 375]) {
  test.describe(`${width}px`, () => {
    test.use({ viewport: { width, height: 740 }, isMobile: true, hasTouch: true });

    test(`${width}px: название и подпись состояния не заходят под «Начать»/«⋯»`, async ({ page }, testInfo) => {
      await withOccurrenceStates(page);
      const { apiFailures } = await openAppAs(page, 900_016);
      await page.getByRole("button", { name: "Планы" }).click();
      const states = page.getByTestId("plans-row-state");
      await expect(states).toHaveCount(2);
      await expect(states.filter({ hasText: "Не уместится на этой неделе" })).toHaveCount(1);

      const rows = page.getByTestId("plans-row").filter({ has: page.getByTestId("plans-row-state") });
      for (let i = 0; i < 2; i += 1) {
        const report = await rows.nth(i).evaluate((row) => {
          const box = (selector: string) => row.querySelector(selector)?.getBoundingClientRect() ?? null;
          const actions = [box(".plans-start"), box(".plans-more")].filter((r): r is DOMRect => r !== null);
          const texts = [box(".plans-row-title"), box(".plans-row-state, [data-testid=plans-row-state]")]
            .filter((r): r is DOMRect => r !== null);
          const title = row.querySelector(".plans-row-title") as HTMLElement;
          const state = row.querySelector("[data-testid=plans-row-state]") as HTMLElement;
          return {
            texts: texts.map((r) => ({ left: r.left, right: r.right, top: r.top, bottom: r.bottom })),
            actions: actions.map((r) => ({ left: r.left, right: r.right, top: r.top, bottom: r.bottom })),
            rowRight: row.getBoundingClientRect().right,
            titleClipped: title.scrollWidth > title.clientWidth + 1,
            stateClipped: state.scrollWidth > state.clientWidth + 1,
          };
        });
        for (const text of report.texts) {
          for (const action of report.actions) {
            expect(intersects(text as DOMRect, action as DOMRect), `строка ${i}: текст под кнопкой ${JSON.stringify({ text, action })}`).toBe(false);
          }
          expect(text.right).toBeLessThanOrEqual(report.rowRight + 0.5);
        }
        expect(report.stateClipped, `строка ${i}: подпись состояния обрезана`).toBe(false);
        expect(report.titleClipped, `строка ${i}: короткое название «Подтягивания» обрезано`).toBe(false);
      }
      await rows.first().screenshot({ path: testInfo.outputPath(`plans-row-${width}.png`) });
      expect(apiFailures).toEqual([]);
    });
  });
}
