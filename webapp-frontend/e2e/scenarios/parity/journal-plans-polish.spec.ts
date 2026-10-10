import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";

import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs, useLiveEngineV1 } from "../../fixtures/setup";

// issue #306: сценарий экрана движка v1 (сессии engine_version = 1) — новые старты здесь на v1.
useLiveEngineV1(test);

// #277 (Journal/Plans leftovers): 1) карточка Журнала на 320 не режет бейдж типа и деградирует по названию (2 строки);
// 2) выполненная строка дня Планов (1/1) показывает «✓ 1/1» (галочка — CSS, текст счётчика «1/1») и вторичное «Повторить», а не главное «Начать: …»;
// 3) форма «Изменить» запись Журнала имеет круглую «← Назад», равную «Отмене» (ничего не пишет).
// Seed: scripts/e2e_seed.py journal_plans_polish — длинное название тренировки плана, запись задним числом,
// план-строка «Подтягивания» уже выполнена. Тесты только читают; пользователь на ширину/тему и retry.
const BASE = {
  320: { light: 998_301, dark: 998_311 },
  390: { light: 998_321, dark: 998_331 },
} as const;
const SHOTS = "/tmp/jpfix-shots";
const LONG_TITLE = "Силовая тренировка верхней части тела с подтягиваниями и отжиманиями";

async function shot(page: Page, name: string) {
  mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: `${SHOTS}/${name}.png` });
}

for (const width of WIDTHS) {
  for (const theme of ["light", "dark"] as const) {
    const id = BASE[width][theme];
    test.describe(`Journal/Plans polish @${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: 800 } });
      test.setTimeout(90_000);

      test("карточка Журнала: бейдж типа не обрезан, название — до 2 строк, полный текст остаётся в DOM", async ({ page }, testInfo) => {
        const { apiFailures } = await openAppAs(page, id + testInfo.retry, { theme });
        await openTab(page, "Журнал");
        const cards = page.getByTestId("journal-card");
        await expect(cards).toHaveCount(3);
        await shot(page, `journal-${width}-${theme}`);

        const expected = [
          { kind: "plan", badge: "По плану", title: LONG_TITLE },
          { kind: "backdated", badge: "Записана задним числом", title: "Тренировка" },
        ];
        for (const { kind, badge, title } of expected) {
          const card = page.locator(`[data-testid="journal-card"][data-kind="${kind}"]`).filter({
            has: page.locator(".journal-card-name", { hasText: title === "Тренировка" ? /^Тренировка$/ : title }),
          });
          await expect(card).toHaveCount(1);
          const badgeEl = card.getByTestId("journal-kind-badge");
          await expect(badgeEl).toHaveText(badge);
          const nameEl = card.locator(".journal-card-name");
          await expect(nameEl).toHaveText(title); // полный текст — для скринридера/копирования
          const metrics = await card.evaluate((node) => {
            const b = node.querySelector<HTMLElement>('[data-testid="journal-kind-badge"]')!;
            const n = node.querySelector<HTMLElement>(".journal-card-name")!;
            const cardBox = node.getBoundingClientRect();
            const bb = b.getBoundingClientRect();
            const nb = n.getBoundingClientRect();
            const lh = parseFloat(getComputedStyle(n).lineHeight) || parseFloat(getComputedStyle(n).fontSize) * 1.3;
            return {
              badgeClipped: b.scrollWidth > b.clientWidth + 1,
              badgeInside: bb.left >= cardBox.left && bb.right <= cardBox.right + 0.5,
              nameLines: Math.round(nb.height / lh),
              nameWidth: nb.width,
              cardWidth: cardBox.width,
            };
          });
          expect(metrics.badgeClipped, `бейдж «${badge}» не обрезан`).toBe(false);
          expect(metrics.badgeInside, `бейдж «${badge}» внутри карточки`).toBe(true);
          expect(metrics.nameLines, "название ≤ 2 строк").toBeLessThanOrEqual(2);
          if (width === 320) {
            // название получает всю ширину строки (приоритет над бейджем/временем)
            expect(metrics.nameWidth).toBeGreaterThan(metrics.cardWidth * 0.6);
          }
        }
        await expectNoHorizontalOverflow(page, "Журнал: карточки");
        expect(apiFailures).toEqual([]);
      });

      test("Планы: выполненная строка 1/1 — «✓ 1/1» и вторичное «Повторить», без главного «Начать: …»", async ({ page }, testInfo) => {
        const { apiFailures } = await openAppAs(page, id + testInfo.retry, { theme });
        await openTab(page, "Планы");
        const rows = page.getByTestId("plans-row");
        await expect(rows.first()).toBeVisible();
        const done = page.locator('[data-testid="plans-row"][data-done="true"]');
        await expect(done).toHaveCount(1);
        await shot(page, `plans-${width}-${theme}`);
        await expect(done.getByTestId("plan-item-counter")).toHaveText("1/1");
        expect(await done.getByTestId("plan-item-counter").evaluate((el) => getComputedStyle(el, "::before").content)).toContain("✓");
        await expect(done.getByRole("button", { name: /^Начать: / })).toHaveCount(0);
        const again = done.getByRole("button", { name: /^Повторить: / });
        await expect(again).toHaveCount(1);
        expect((await again.boundingBox())!.height).toBeGreaterThanOrEqual(44);
        await expectNoHorizontalOverflow(page, "Планы: выполненная строка");
        // названия не теряются на узком экране
        await expect(done.locator(".plans-row-title")).not.toHaveText("");
        expect(apiFailures).toEqual([]);
      });

      test("форма «Изменить»: круглая «← Назад» = «Отмена», запись не меняется", async ({ page }, testInfo) => {
        const { apiFailures } = await openAppAs(page, id + testInfo.retry, { theme, backButton: true });
        const writes: string[] = [];
        page.on("request", (request) => {
          if (request.url().includes("/api/") && request.method() !== "GET") {
            writes.push(`${request.method()} ${request.url()}`);
          }
        });
        await openTab(page, "Журнал");
        const card = page.getByTestId("journal-card").filter({ hasText: LONG_TITLE });
        await card.click();
        await page.getByTestId("journal-sheet-edit").click();
        const form = page.getByTestId("journal-edit-form");
        await expect(form).toBeVisible();
        const back = form.getByRole("button", { name: "← Назад" });
        await expect(back).toBeVisible();
        const box = (await back.boundingBox())!;
        expect(box.width).toBeGreaterThanOrEqual(40);
        expect(box.height).toBeGreaterThanOrEqual(40);
        // кнопка вверху формы (над заголовком), а не внизу
        const titleBox = (await form.getByText("Изменить тренировку").boundingBox())!;
        expect(box.y).toBeLessThan(titleBox.y);
        await shot(page, `journal-edit-${width}-${theme}`);

        await form.getByLabel("Подход 1: значение").fill("99");
        await back.click();
        await expect(form).toHaveCount(0);
        await expect(page.getByTestId("journal-card")).toHaveCount(3);
        expect(writes, "«Назад» не пишет данных").toEqual([]);

        // значение не сохранилось
        await card.click();
        await page.getByTestId("journal-sheet-edit").click();
        await expect(page.getByTestId("journal-edit-form").getByLabel("Подход 1: значение")).toHaveValue("8");
        expect(writes).toEqual([]);
        expect(apiFailures).toEqual([]);
      });
    });
  }
}
