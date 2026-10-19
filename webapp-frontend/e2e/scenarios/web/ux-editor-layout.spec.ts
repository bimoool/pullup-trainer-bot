import { expect, test, type Locator, type Page } from "@playwright/test";

import { collectConsoleErrors, collectUnexpectedApiFailures } from "../../fixtures/assertions";

// Браузерный режим (вход test-login): форма создания плана, редактор и расписание — оболочка («Назад», «Выйти»)
// не налезает на заголовок формы, нет горизонтального overflow, листы в окне, кнопки не перекрыты.
// Сиды: ux_editor_course 941031 (desktop 1280) и 941032 (mobile 390) — сценарий ничего не сохраняет.

function overlaps(a: { x: number; y: number; width: number; height: number }, b: typeof a): boolean {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

async function expectNoOverlap(page: Page, shell: Locator, title: Locator, what: string) {
  await page.evaluate(() => window.scrollTo(0, 0));
  const a = await shell.boundingBox();
  const b = await title.boundingBox();
  if (a && b) {
    expect(overlaps(a, b), `${what} налезает на заголовок формы`).toBe(false);
  }
}

async function expectInViewport(page: Page, target: Locator, what: string) {
  await target.scrollIntoViewIfNeeded();
  const box = await target.boundingBox();
  const { width, height } = page.viewportSize()!;
  expect(box, what).not.toBeNull();
  expect(box!.x, `${what}: левее окна`).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width, `${what}: правее окна`).toBeLessThanOrEqual(width);
  expect(box!.y + box!.height, `${what}: ниже окна`).toBeLessThanOrEqual(height);
  const hit = await target.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return top === el || el.contains(top);
  });
  expect(hit, `${what}: перекрыт`).toBe(true);
}

test("браузер: форма создания, редактор, расписание — без наложений и overflow", async ({ page }, info) => {
  const consoleErrors = collectConsoleErrors(page);
  const apiFailures = collectUnexpectedApiFailures(page, []);
  const login = await page.request.post("/api/web-auth/test-login", {
    data: { telegram_id: info.project.name === "web-mobile" ? 941_032 : 941_031 },
  });
  expect(login.status()).toBe(200);
  await page.goto("/");
  await page.getByRole("button", { name: "Планы" }).first().click();
  await page.getByTestId("plans-custom-plan").click();

  const title = page.getByTestId("plan-create-screen").locator(".plan-title").first();
  for (const id of ["web-back", "sign-out"]) {
    const shell = page.getByTestId(id);
    if (await shell.count()) {
      await expectNoOverlap(page, shell.first(), title, `«${id}»`);
    }
  }
  const noOverflow = async (where: string) => {
    const { scrollWidth, clientWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth,
    }));
    expect(scrollWidth, `overflow: ${where}`).toBeLessThanOrEqual(clientWidth);
  };
  await noOverflow("форма создания");
  const name = page.getByTestId("plan-create-name");
  const box = await name.boundingBox();
  expect(box!.width, "поле «Название» слишком узкое").toBeGreaterThanOrEqual(Math.min(280, page.viewportSize()!.width - 64));

  // «Назад» в странице: шаг 2 → шаг 1 → «Планы»
  const first = await page.locator('[data-testid^="plan-create-workout-"]').first().getAttribute("data-testid");
  await page.getByTestId(first!).check();
  await page.getByTestId("plan-create-next").click();
  await expect(page.getByTestId("create-total-1")).toBeVisible();
  await page.getByTestId("web-back").click();
  await expect(page.getByTestId("plan-create-name")).toBeVisible();
  await page.getByTestId("web-back").click();
  await expect(page.getByTestId("plans-custom-section")).toBeVisible();

  // шторка остановки: в окне, обе кнопки достижимы
  await page.getByTestId("plans-custom-plan-stop").click();
  await expectInViewport(page, page.getByTestId("plans-stop-ok"), "«Остановить план»");
  await expectInViewport(page, page.getByTestId("plans-stop-cancel"), "«Отмена»");
  await page.getByTestId("plans-stop-cancel").click();

  await page.getByTestId("plans-custom-plan-edit").click();
  await noOverflow("редактор");
  await expectNoOverlap(page, page.getByTestId("web-back"), page.getByTestId("plan-editor-screen").locator(".plan-title").first(), "«Назад»");
  await page.getByTestId("editor-schedule-1").click();
  await noOverflow("расписание");
  await expectNoOverlap(page, page.getByTestId("web-back"), page.getByTestId("week-schedule-screen").locator(".plan-title").first(), "«Назад»");
  await page.getByTestId("web-back").click();
  await expect(page.getByTestId("plan-editor-screen")).toBeVisible();

  expect(consoleErrors).toEqual([]);
  expect(apiFailures).toEqual([]);
});
