import { expect, type Page, test } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

/**
 * Правка записанного подхода на узком экране (аудиты staging cb1593c и 6475bc0). Сид: live_engine (930622–930625),
 * «Движок: подходы» — отдых 6 с после первого подхода, затем работа второго без «Начать сейчас».
 *  - «Сохранить подход» не перекрыт липкой нижней панелью, а «Пауза» при открытой правке остаётся доступной;
 *  - отдых сам переходит в работу (таймер не останавливается), а несохранённая правка не исчезает молча;
 *  - «Отменить правку» закрывает форму без события на сервер, значение подхода прежнее.
 */
test.setTimeout(90_000);

async function startAndLogFirstSet(page: Page, telegramId: number) {
  const opened = await openAppAs(page, telegramId);
  await page.getByRole("button", { name: "Планы" }).click();
  const group = page.locator(".plan-week-day-group").filter({ hasText: /^Движок: подходы/ });
  await group.getByRole("button", { name: /^Начать: / }).first().click();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл", { timeout: 10_000 });
  await page.getByLabel("Результат подхода").fill("7");
  await page.getByTestId("engine-submit").click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых", { timeout: 10_000 });
  return opened;
}

const overlapsTransport = (page: Page, testIdOrName: { testId?: string; name?: string }) => {
  const target = testIdOrName.testId ? page.getByTestId(testIdOrName.testId) : page.getByRole("button", { name: testIdOrName.name! });
  return target.evaluate((element) => {
    const box = element.getBoundingClientRect();
    return [...document.querySelectorAll(".live-transport")].some((panel) => {
      if (panel.contains(element)) {
        return false;
      }
      const p = panel.getBoundingClientRect();
      return p.top < box.bottom && p.bottom > box.top && p.left < box.right && p.right > box.left;
    });
  });
};

for (const [width, height, telegramId] of [[320, 568, 930_622], [375, 667, 930_624]] as const) {
  test.describe(`${width}×${height}`, () => {
    test.use({ viewport: { width, height }, isMobile: true, hasTouch: true });

    test(`${width}px: правка переживает переход отдыха в работу, «Пауза» доступна, сохранение не перекрыто`, async ({ page }) => {
      const { apiFailures } = await startAndLogFirstSet(page, telegramId);
      const corrections: string[] = [];
      page.on("request", (request) => {
        if (request.url().includes("/events") && request.method() === "POST" && (request.postData() ?? "").includes("correct_previous")) {
          corrections.push(request.postData() ?? "");
        }
      });

      await page.getByTestId("engine-edit-last").click();
      const input = page.getByLabel("Исправить подход");
      for (const focused of [true, false]) {
        if (!focused) {
          await input.blur();
        }
        expect(await overlapsTransport(page, { name: "Сохранить подход" }), `перекрыто (фокус: ${focused})`).toBe(false);
        expect(await overlapsTransport(page, { testId: "engine-edit-cancel" })).toBe(false);
      }
      await input.fill("9");

      // Пауза при открытой правке: кнопка есть и нажимается; снимаем паузу — отдых идёт дальше сам.
      await page.getByTestId("pause-toggle").scrollIntoViewIfNeeded();
      await expect(page.getByTestId("pause-toggle")).toHaveText("Пауза");
      await page.getByTestId("pause-toggle").click();
      await expect(page.locator(".live-screen")).toHaveAttribute("data-paused", "true");
      await page.getByTestId("pause-toggle").click();
      await expect(page.locator(".live-screen")).not.toHaveAttribute("data-paused", "true");

      // Отдых закончился сам → работа второго подхода; несохранённая правка на месте, ничего не отправлено.
      await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл", { timeout: 15_000 });
      await expect(page.getByLabel("Исправить подход")).toHaveValue("9");
      await expect(page.getByTestId("engine-edit-pending")).toBeVisible();
      expect(corrections).toEqual([]);
      expect(await overlapsTransport(page, { name: "Сохранить подход" })).toBe(false);

      const posted = page.waitForResponse((r) => r.url().includes("/events") && r.request().method() === "POST" && r.ok()
        && (r.request().postData() ?? "").includes("correct_previous"));
      await page.getByRole("button", { name: "Сохранить подход" }).click();
      const body = await (await posted).json();
      const first = body.engine.state.logs.find((log: { set_index: number; is_extra: boolean }) => log.set_index === 0 && !log.is_extra);
      expect(first.value).toBe(9);
      await expect(page.getByTestId("engine-edit-form")).toHaveCount(0);
      await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл"); // правка фазу не меняет
      expect(apiFailures).toEqual([]);
    });
  });
}

test.describe("320×568 отмена", () => {
  test.use({ viewport: { width: 320, height: 568 }, isMobile: true, hasTouch: true });

  test("«Отменить правку» закрывает форму без события на сервер", async ({ page }) => {
    const { apiFailures } = await startAndLogFirstSet(page, 930_623);
    const corrections: string[] = [];
    page.on("request", (request) => {
      if (request.url().includes("/events") && request.method() === "POST" && (request.postData() ?? "").includes("correct_previous")) {
        corrections.push(request.postData() ?? "");
      }
    });
    await page.getByTestId("engine-edit-last").click();
    await page.getByLabel("Исправить подход").fill("12");
    await page.getByTestId("engine-edit-cancel").click();
    await expect(page.getByTestId("engine-edit-form")).toHaveCount(0);
    await expect(page.getByTestId("log-panel-summary")).toContainText("7");
    await page.waitForTimeout(500);
    expect(corrections).toEqual([]);
    expect(apiFailures).toEqual([]);
  });
});

for (const [width, height, telegramId] of [[320, 568, 930_625], [375, 667, 930_626]] as const) {
  test.describe(`${width}×${height} кнопки`, () => {
    test.use({ viewport: { width, height }, isMobile: true, hasTouch: true });

    test(`${width}px: кнопки нижней панели в отдыхе между блоками не обрезаны`, async ({ page }) => {
      const { apiFailures } = await openAppAs(page, telegramId);
      await page.getByRole("button", { name: "Планы" }).click();
      await page.locator(".plan-week-day-group").filter({ hasText: /^Движок: блоки/ }).getByRole("button", { name: /^Начать: / }).first().click();
      await page.getByRole("button", { name: "Начать", exact: true }).click();
      await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл", { timeout: 10_000 });
      await page.getByLabel("Результат подхода").fill("3");
      await page.getByTestId("engine-submit").click();
      await expect(page.getByTestId("engine-phase")).toHaveText("Отдых", { timeout: 10_000 });
      // Отдых блока: «Начать сейчас», «Пауза», «+ Ещё подход» — все три, ни одна подпись не обрезана многоточием.
      await expect(page.getByTestId("extra-set-button")).toBeVisible();
      const buttons = page.locator(".live-transport button");
      const report = await buttons.evaluateAll((elements) => elements.map((element) => {
        const clipped = [element, ...element.querySelectorAll("*")].some((node) => {
          const el = node as HTMLElement;
          return el.scrollWidth > el.clientWidth + 1;
        });
        const box = element.getBoundingClientRect();
        return { text: element.textContent?.trim() ?? "", clipped, right: box.right };
      }));
      expect(report.map((b) => b.text)).toEqual(expect.arrayContaining(["Начать сейчас", "Пауза", "+ Ещё подход"]));
      for (const button of report) {
        expect(button.clipped, `«${button.text}» обрезана`).toBe(false);
        expect(button.right).toBeLessThanOrEqual(width);
      }
      expect(apiFailures).toEqual([]);
    });
  });
}
