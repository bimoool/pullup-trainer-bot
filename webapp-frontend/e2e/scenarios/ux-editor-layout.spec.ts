import { expect, test, type Locator, type Page } from "@playwright/test";

import { openAppAs } from "../fixtures/setup";

// Раскладка новых экранов плана (волна 3, пункт D): форма создания (оба шага), редактор, расписание недели,
// листы подтверждения и переноса. 320/360/390 px × светлая/тёмная тема + экранная клавиатура (высота 740 → 400).
// Проверки геометрии: нет горизонтального overflow, заголовок и поле «Название» целиком в окне, последний
// элемент и кнопки действий достижимы и не перекрыты нижней навигацией/другими элементами, лист целиком в окне.
// Сид ux_editor_course 941030 (свой план + курс) — сценарий ничего не сохраняет.
const TELEGRAM_ID = 941_030;
const KEYBOARD_HEIGHT = 400;

async function expectNoOverflow(page: Page, where: string) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth, `горизонтальный overflow: ${where}`).toBeLessThanOrEqual(clientWidth);
}

async function expectReachable(page: Page, target: Locator, what: string) {
  // scrollIntoViewIfNeeded считает частично видимый элемент «видимым» — центрируем явно.
  await target.evaluate((el) => el.scrollIntoView({ block: "center" }));
  const box = await target.boundingBox();
  const { width: vw, height: vh } = page.viewportSize()!;
  expect(box, `нет бокса: ${what}`).not.toBeNull();
  expect(box!.x, `${what} левее окна`).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width, `${what} правее окна`).toBeLessThanOrEqual(vw);
  expect(box!.y, `${what} выше окна`).toBeGreaterThanOrEqual(0);
  expect(box!.y + box!.height, `${what} ниже окна`).toBeLessThanOrEqual(vh);
  const hit = await target.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return top === el || el.contains(top);
  });
  expect(hit, `${what} перекрыт другим элементом`).toBe(true);
}

/** Последний элемент контента страницы не уходит под нижнюю навигацию, если прокрутить в самый конец. */
async function expectEndClearOfTabbar(page: Page, last: Locator, what: string) {
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await last.scrollIntoViewIfNeeded();
  const tabbar = await page.locator(".bottom-tabbar").boundingBox();
  const box = await last.boundingBox();
  if (tabbar && box) {
    expect(box.y + box.height, `${what} под нижней навигацией`).toBeLessThanOrEqual(tabbar.y + 1);
  }
}

async function expectTitleVisible(page: Page, title: Locator, what: string) {
  await page.evaluate(() => window.scrollTo(0, 0));
  const box = await title.boundingBox();
  expect(box, `нет заголовка: ${what}`).not.toBeNull();
  expect(box!.y, `заголовок ${what} обрезан сверху`).toBeGreaterThanOrEqual(0);
  const hit = await title.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + 4, r.top + r.height / 2);
    return top === el || el.contains(top);
  });
  expect(hit, `заголовок ${what} перекрыт`).toBe(true);
}

for (const theme of ["light", "dark"] as const) {
  for (const width of [320, 360, 390]) {
    test.describe(`${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: 740 }, isMobile: true, hasTouch: true });

      test("форма создания: заголовок, поле названия, клавиатура, кнопки", async ({ page }) => {
        const { apiFailures } = await openAppAs(page, TELEGRAM_ID, { theme });
        await page.getByRole("button", { name: "Планы" }).click();
        await page.getByTestId("plans-custom-plan").click();
        const screen = page.getByTestId("plan-create-screen");
        await expectTitleVisible(page, screen.locator(".plan-title").first(), "формы создания");
        const name = page.getByTestId("plan-create-name");
        const box = await name.boundingBox();
        expect(box!.width, "поле «Название» слишком узкое").toBeGreaterThanOrEqual(width - 64);
        await expectNoOverflow(page, "форма, шаг 1");

        // клавиатура: поле остаётся достижимым, после возврата нет смещения
        await name.focus();
        await page.setViewportSize({ width, height: KEYBOARD_HEIGHT });
        await expectReachable(page, name, "поле «Название» при клавиатуре");
        await expectNoOverflow(page, "форма с клавиатурой");
        await page.setViewportSize({ width, height: 740 });

        const workoutId = await firstWorkoutId(page);
        await page.getByTestId(`plan-create-workout-${workoutId}`).check();
        await expectEndClearOfTabbar(page, page.getByTestId("plan-create-cancel"), "«Отмена» формы");
        await expectReachable(page, page.getByTestId("plan-create-next"), "«Далее»");
        await page.getByTestId("plan-create-next").click();

        await expectNoOverflow(page, "форма, шаг 2");
        await expectReachable(page, page.getByTestId(`create-inc-1-${workoutId}`), "«+» количества");
        await expectEndClearOfTabbar(page, page.getByTestId("plan-create-cancel"), "«Назад» матрицы");
        await page.getByTestId("plan-create-save").click(); // у 941030 есть активный план → лист замены
        const sheet = page.getByTestId("plan-replace-confirm");
        await expect(sheet).toBeVisible();
        await expectReachable(page, page.getByTestId("plan-replace-ok"), "«Заменить»");
        await expectReachable(page, page.getByTestId("plan-replace-cancel"), "«Отмена» листа замены");
        await expectNoOverflow(page, "лист замены");
        await page.getByTestId("plan-replace-cancel").click();
        expect(apiFailures).toEqual([]);
      });

      test("редактор, расписание, лист остановки и перенос", async ({ page }) => {
        const { apiFailures } = await openAppAs(page, TELEGRAM_ID, { theme });
        await page.getByRole("button", { name: "Планы" }).click();

        await page.getByTestId("plans-custom-plan-stop").click();
        await expectReachable(page, page.getByTestId("plans-stop-ok"), "«Остановить план» в листе");
        await expectReachable(page, page.getByTestId("plans-stop-cancel"), "«Отмена» листа остановки");
        await expectNoOverflow(page, "лист остановки");
        await page.getByTestId("plans-stop-cancel").click();

        await page.getByTestId("plans-custom-plan-edit").click();
        const editor = page.getByTestId("plan-editor-screen");
        await expectTitleVisible(page, editor.locator(".plan-title").first(), "редактора");
        await expectNoOverflow(page, "редактор");
        for (const week of [1, 4]) {
          await expectReachable(page, page.getByTestId(`editor-total-${week}`), `итог недели ${week}`);
        }
        const inc = editor.locator('[data-testid^="editor-inc-4-"]').first();
        await expectReachable(page, inc, "«+» последней недели");
        await expectEndClearOfTabbar(page, editor.getByRole("button", { name: "Готово" }), "«Готово» редактора");

        await page.getByTestId("editor-delete-3").click();
        await expectReachable(page, page.getByTestId("editor-confirm-ok"), "«Удалить» в листе");
        await expectReachable(page, page.getByTestId("editor-confirm-cancel"), "«Отмена» листа удаления");
        await page.getByTestId("editor-confirm-cancel").click();

        await page.getByTestId("editor-schedule-1").click();
        const schedule = page.getByTestId("week-schedule-screen");
        await expectTitleVisible(page, schedule.locator(".plan-title").first(), "расписания");
        await expectNoOverflow(page, "расписание");
        await expectReachable(page, schedule.locator('[data-testid^="schedule-inc-"]').last(), "«+» последнего дня");
        await expectEndClearOfTabbar(page, schedule.getByRole("button", { name: "Готово" }), "«Готово» расписания");
        await schedule.getByRole("button", { name: "Готово" }).click();
        await editor.getByRole("button", { name: "Готово" }).click();

        // перенос: лист целиком в окне, «Отмена» достижима
        await page.getByTestId("plans-row-more").first().click();
        await page.getByTestId("plans-sheet-move").click();
        await expectNoOverflow(page, "лист переноса");
        await expectReachable(page, page.getByTestId("move-cancel"), "«Отмена» листа переноса");
        await page.getByTestId("move-cancel").click();
        expect(apiFailures).toEqual([]);
      });
    });
  }
}

async function firstWorkoutId(page: Page): Promise<string> {
  const id = await page.locator('[data-testid^="plan-create-workout-"]').first().getAttribute("data-testid");
  return id!.replace("plan-create-workout-", "");
}
