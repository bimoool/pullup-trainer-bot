import { expect, test, type Locator, type Page } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";

import { overridePlanToday, pickPlanAction, pickRowAction, watchServerPlanToday } from "../../fixtures/plans";
import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import { isTelegramBackButtonVisible, pressTelegramBackButton } from "../../fixtures/telegramMock";

// #286 B — экран «Планы»: строка дня (цветная полоска + название + чип «0/1» + «Начать» + «⋯»), нижние листы
// действий, карточка плана «Неделя n из N» + полоса прогресса, блок «Сегодня», вкладки с подчёркиванием.
// Сиды: builder_workouts (991001–991014, шесть пользовательских тренировок Пн–Сб, 991003/4 мутируются) и
// plans_overview (990101/990102) и plan_week_stepper (990001/990002) — только чтение: лист открывается и закрывается.

/** Захват для before/after (UX_CAPTURE_DIR=/tmp/ux-t4plans UX_LABEL=before|after); без переменной — пропуск. */
const CAPTURE_DIR = process.env.UX_CAPTURE_DIR;
const LABEL = process.env.UX_LABEL ?? "after";
async function shot(page: Page, width: number, theme: string, name: string) {
  if (!CAPTURE_DIR) {
    return;
  }
  const dir = path.join(CAPTURE_DIR, LABEL, String(width));
  fs.mkdirSync(dir, { recursive: true });
  await page.waitForTimeout(200);
  await page.screenshot({ path: path.join(dir, `${name}_${theme}.png`), fullPage: true });
}

const ROWS_USERS = { 320: { id: 991_001, theme: "light" }, 390: { id: 991_002, theme: "dark" } } as const;
const MUTATE_USERS = { 320: { id: 991_003, theme: "light" }, 390: { id: 991_004, theme: "dark" } } as const;
const OVERVIEW_USERS = { 320: { id: 990_101, theme: "light" }, 390: { id: 990_102, theme: "dark" } } as const;
// 990001/990002: текущая неделя — «Планка» 1/2 + «Отжимания» 0/1 → «1 из 3».
const PROGRESS_USERS = { 320: { id: 990_001, theme: "light" }, 390: { id: 990_002, theme: "dark" } } as const;
// builder_workouts: тренировка на день недели (0 = пн … 5 = сб); сегодня — одна из них, кроме воскресенья.
const WORKOUT_BY_DAY = ["Только reps", "Только time", "Только max", "Только interval", "Смешанная", "Дубли"];
const DANGER_RGB = "rgb(229, 72, 77)"; // --vp-cat-1

const visibleButtons = (row: Locator) => row.locator("button:visible");

for (const width of WIDTHS) {
  const rows = ROWS_USERS[width as 320 | 390];
  const mutate = MUTATE_USERS[width as 320 | 390];
  const overview = OVERVIEW_USERS[width as 320 | 390];
  const progressUser = PROGRESS_USERS[width as 320 | 390];

  test.describe(`Plans visual @${width}px ${rows.theme}`, () => {
    test.use({ viewport: { width, height: 760 } });

    test("строка дня: одна кнопка + «⋯», название в одну строку, шаблон полосы/чипа; блок «Сегодня»", async ({ page }) => {
      const server = watchServerPlanToday(page);
      const { consoleErrors, apiFailures } = await openAppAs(page, rows.id, { theme: rows.theme });
      await openTab(page, "Планы");
      await expect(page.getByTestId("plan-week-label")).toBeVisible();

      // Название недели «Неделя 1 · 28 сен – 4 окт» — в одну строку и на 320.
      const labelHeight = await page.getByTestId("plan-week-label").evaluate((el) => el.getBoundingClientRect().height);
      expect(labelHeight, "название недели в одну строку").toBeLessThan(24);

      const dayRows = page.getByTestId("plans-row");
      await expect(dayRows).toHaveCount(6);
      for (let index = 0; index < 6; index += 1) {
        const row = dayRows.nth(index);
        await expect(row.locator(".plans-row-bar")).toBeVisible();
        // «Начать» + «⋯»: не больше двух кнопок, из них ровно одна — «⋯».
        await expect(visibleButtons(row)).toHaveCount(2);
        await expect(row.getByTestId("plans-row-more")).toHaveCount(1);
        await expect(row.getByRole("button", { name: "Начать", exact: true })).toHaveCount(1);
        await expect(row.getByRole("button", { name: "Перенести" })).toHaveCount(0);
        await expect(row.getByRole("button", { name: "Убрать из плана" })).toHaveCount(0);
        await expect(row.getByRole("button", { name: "Редактировать тренировку" })).toHaveCount(0);
        await expect(row.getByTestId("plan-item-counter")).toHaveText("0/1");
        const geometry = await row.evaluate((el) => {
          const title = el.querySelector(".plans-row-title") as HTMLElement;
          const main = el.querySelector(".plans-row-main") as HTMLElement;
          return {
            titleHeight: title.getBoundingClientRect().height, rowHeight: main.getBoundingClientRect().height,
            truncated: title.scrollWidth > title.clientWidth,
          };
        });
        expect(geometry.titleHeight, `название строки ${index + 1} в одну строку`).toBeLessThan(24);
        expect(geometry.rowHeight, `строка ${index + 1} не переносится`).toBeLessThan(60);
        expect(geometry.truncated, `название строки ${index + 1} не обрезано`).toBe(false);
      }

      // «Сегодня»: блок с сегодняшней тренировкой и «Начать» (воскресенье — пустой день, блока нет).
      // День — по plan.today сервера (дата пользователя), не по часам машины (#288).
      const todayIndex = await server.weekdayIndex();
      if (todayIndex <= 5) {
        const today = page.getByTestId("plans-today");
        await expect(today).toBeVisible();
        await expect(today.getByTestId("plans-today-row")).toHaveCount(1);
        await expect(today.getByRole("button", { name: `Начать: ${WORKOUT_BY_DAY[todayIndex]}` })).toBeVisible();
      } else {
        await expect(page.getByTestId("plans-today")).toHaveCount(0);
      }

      // Без акцентного кольца на карточке текущей недели; вкладки — с подчёркиванием.
      const card = await page.locator(".plans-week-card").evaluate((el) => {
        const style = getComputedStyle(el);
        return { shadow: style.boxShadow, border: style.borderTopWidth };
      });
      expect(card.border).toBe("0px");
      expect(card.shadow).not.toContain("1.5px");
      const tab = await page.getByRole("tab", { name: "Сейчас" }).evaluate((el) => {
        const style = getComputedStyle(el);
        return { underline: parseFloat(style.borderBottomWidth), radius: parseFloat(style.borderTopLeftRadius) };
      });
      expect(tab.underline).toBeGreaterThanOrEqual(2);
      expect(tab.radius).toBe(0);

      await expectNoHorizontalOverflow(page, "Планы: строки дня");
      await shot(page, width, rows.theme, "plans_rows");
      expect(consoleErrors).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("«Сегодня» идёт от plan.today сервера, а не от часов устройства; вне недели — блока нет; пересчёт при возврате в приложение (#288)", async ({ page }) => {
      const server = watchServerPlanToday(page);
      let override: string | null = null;
      await overridePlanToday(page, () => override);
      // Возраст плана считаем по Date.now: сдвигаем его, не трогая часы страницы целиком.
      await page.addInitScript(() => {
        const real = Date.now.bind(Date);
        (window as unknown as { __skew: number }).__skew = 0;
        Date.now = () => real() + (window as unknown as { __skew: number }).__skew;
      });
      const day = (iso: string, offset: number) => new Date(Date.parse(`${iso}T00:00:00Z`) + offset * 86_400_000).toISOString().slice(0, 10);
      const { consoleErrors, apiFailures } = await openAppAs(page, rows.id, { theme: rows.theme });
      await openTab(page, "Планы");
      await expect(page.getByTestId("plan-week-label")).toBeVisible();
      const realToday = await server.today();
      const weekday = await server.weekdayIndex();
      const monday = day(realToday, -weekday);
      const reload = async () => {
        await page.evaluate(() => { (window as unknown as { __skew: number }).__skew += 120_000; });
        await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
      };

      // сервер говорит «среда» (индекс 2), чего бы ни показывали часы машины
      override = day(monday, 2);
      await reload();
      const today = page.getByTestId("plans-today");
      await expect(today.getByRole("button", { name: `Начать: ${WORKOUT_BY_DAY[2]}` })).toBeVisible();
      await expect(today.getByTestId("plans-today-row")).toHaveCount(1);

      // «Вчера ночью приложение осталось открытым»: сервер уже в следующей неделе — блока «Сегодня» нет
      override = day(monday, 7);
      await reload();
      await expect(today).toHaveCount(0);

      // и обратно на воскресенье (индекс 6): день без тренировок — блока нет
      override = day(monday, 6);
      await reload();
      await expect(today).toHaveCount(0);

      // понедельник (0): первая тренировка недели
      override = day(monday, 0);
      await reload();
      await expect(today.getByRole("button", { name: `Начать: ${WORKOUT_BY_DAY[0]}` })).toBeVisible();

      expect(consoleErrors).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("лист «⋯» строки: пункты, «Убрать» красным; Escape, фон, «Отмена» и Telegram BackButton закрывают; фокус возвращается", async ({ page }) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, rows.id, { theme: rows.theme, backButton: true });
      await openTab(page, "Планы");
      const label = page.getByTestId("plan-week-label");
      await expect(label).toBeVisible();
      const more = page.getByTestId("plans-row-more").first();
      const sheet = page.getByTestId("plans-row-sheet");

      await more.click();
      await expect(sheet).toBeVisible();
      await expect(sheet).toHaveAccessibleName("Только reps");
      await expect(sheet.getByRole("button")).toHaveText(["Перенести", "Редактировать тренировку", "Убрать из плана", "Отмена"]);
      const danger = await sheet.getByRole("button", { name: "Убрать из плана" }).evaluate((el) => getComputedStyle(el).color);
      expect(danger).toBe(DANGER_RGB);
      await expectNoHorizontalOverflow(page, "Планы: лист строки");
      await shot(page, width, rows.theme, "plans_row_sheet");
      // фокус ушёл в лист
      await expect.poll(() => page.evaluate(() => document.activeElement?.closest("[role=dialog]") !== null)).toBe(true);

      // Escape → закрыт, фокус на «⋯»
      await page.keyboard.press("Escape");
      await expect(sheet).toHaveCount(0);
      await expect(more).toBeFocused();

      // тап по фону
      await more.click();
      await expect(sheet).toBeVisible();
      await page.mouse.click(width / 2, 20);
      await expect(sheet).toHaveCount(0);

      // «Отмена»
      await more.click();
      await sheet.getByRole("button", { name: "Отмена" }).click();
      await expect(sheet).toHaveCount(0);

      // Telegram BackButton: пока лист открыт, «назад» закрывает его, а не уходит с экрана
      await expect.poll(() => isTelegramBackButtonVisible(page)).toBe(false);
      await more.click();
      await expect(sheet).toBeVisible();
      await expect.poll(() => isTelegramBackButtonVisible(page)).toBe(true);
      await pressTelegramBackButton(page);
      await expect(sheet).toHaveCount(0);
      await expect(label).toBeVisible();
      await expect.poll(() => isTelegramBackButtonVisible(page)).toBe(false);

      // «Редактировать тренировку» открывает редактор, BackButton ведёт назад в «Планы»
      await pickRowAction(page, "Редактировать тренировку");
      await expect(page.getByText("Редактировать тренировку")).toBeVisible();
      await pressTelegramBackButton(page); // редактор → карточка тренировки
      await expect(page.getByTestId("workout-detail")).toBeVisible();
      await pressTelegramBackButton(page); // → «Мои тренировки»
      await pressTelegramBackButton(page); // → «Планы»
      await expect(label).toBeVisible();

      // «Перенести» открывает экран переноса
      await pickRowAction(page, "Перенести", "Только time");
      await expect(page.getByText("Перенести", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Сохранить" })).toBeVisible();
      await pressTelegramBackButton(page);
      await expect(label).toBeVisible();

      expect(consoleErrors).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("«Убрать из плана» через лист: подтверждение, «Отмена» ничего не меняет, «Убрать» удаляет строку", async ({ page }, testInfo) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, mutate.id + 10 * testInfo.retry, { theme: mutate.theme });
      await openTab(page, "Планы");
      const dayRows = page.getByTestId("plans-row");
      await expect(dayRows).toHaveCount(6);

      await pickRowAction(page, "Убрать из плана", "Дубли");
      await expect(page.getByText("Убрать «Дубли» из плана?")).toBeVisible();
      await expectNoHorizontalOverflow(page, "Планы: подтверждение удаления");
      await page.getByRole("button", { name: "Отмена" }).click();
      await expect(dayRows).toHaveCount(6);
      await expect(page.getByText("Убрать «Дубли» из плана?")).toHaveCount(0);

      await pickRowAction(page, "Убрать из плана", "Дубли");
      await page.getByRole("button", { name: "Убрать", exact: true }).click();
      await expect(dayRows).toHaveCount(5);
      await expect(dayRows.filter({ hasText: "Дубли" })).toHaveCount(0);
      await expectNoHorizontalOverflow(page, "Планы: после удаления");

      expect(consoleErrors).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });

  test.describe(`Plans visual plan card @${width}px ${overview.theme}`, () => {
    test.use({ viewport: { width, height: 760 } });

    test("карточка плана: «Неделя n из N» + полоса прогресса, лист плана («⋯»: копирование недели и «Убрать курс из плана»)", async ({ page }) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, overview.id, { theme: overview.theme, backButton: true });
      await openTab(page, "Планы");
      const course = page.getByTestId("plans-now-inclusion").filter({ hasText: "Обзор: курс" });
      await expect(course).toContainText("Неделя 1 из 8");
      const bar = course.getByTestId("plans-now-progressbar");
      await expect(bar).toHaveAttribute("role", "progressbar");
      await expect(bar).toHaveAttribute("aria-valuenow", "0");
      await expect(bar).toHaveAttribute("aria-valuemax", "6");
      const weekBar = page.getByTestId("plan-week-progressbar");
      await expect(weekBar).toHaveAttribute("aria-valuemax", "7");
      // В карточке курса больше нет текстовых кнопок-пилюль «Убрать курс из плана».
      await expect(course.getByRole("button", { name: "Убрать курс из плана" })).toHaveCount(0);
      await expect(course.getByTestId("plans-plan-more")).toHaveAccessibleName("Действия плана");
      await expectNoHorizontalOverflow(page, "Планы: карточка плана");
      await shot(page, width, overview.theme, "plans_overview");

      const sheet = page.getByTestId("plans-plan-sheet");
      await course.getByTestId("plans-plan-more").click();
      await expect(sheet).toBeVisible();
      await expect(sheet).toHaveAccessibleName("Обзор: курс");
      await expect(sheet.getByRole("button")).toHaveText(["Скопировать неделю → на следующую", "Убрать курс из плана", "Отмена"]);
      const danger = await sheet.getByRole("button", { name: "Убрать курс из плана" }).evaluate((el) => getComputedStyle(el).color);
      expect(danger).toBe(DANGER_RGB);
      await shot(page, width, overview.theme, "plans_plan_sheet");
      await pressTelegramBackButton(page);
      await expect(sheet).toHaveCount(0);
      await page.getByRole("tab", { name: "Сейчас" }).waitFor();

      // «Скопировать неделю» сохраняет подтверждение (в карточке недели); «Отмена» ничего не копирует.
      await pickPlanAction(page, "Скопировать неделю → на следующую", course);
      await expect(page.getByText(/Скопировать свои тренировки и упражнения/)).toBeVisible();
      await page.getByRole("button", { name: "Отмена" }).click();
      await expect(page.getByText(/Скопировать свои тренировки и упражнения/)).toHaveCount(0);
      await expect(page.getByTestId("plan-week-copy-result")).toHaveCount(0);

      // «Убрать курс из плана» сохраняет подтверждение; «Отмена» оставляет курс.
      await pickPlanAction(page, "Убрать курс из плана", course);
      await expect(page.getByText("Убрать курс «Обзор: курс» из плана?")).toBeVisible();
      await expectNoHorizontalOverflow(page, "Планы: подтверждение курса");
      await page.getByRole("button", { name: "Отмена" }).click();
      await expect(page.getByTestId("plans-now-inclusion")).toHaveCount(2);

      expect(consoleErrors).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("полоса прогресса недели отражает «N из M» (1 из 3 → 33%)", async ({ page }) => {
      const { consoleErrors, apiFailures } = await openAppAs(page, progressUser.id, { theme: progressUser.theme });
      await openTab(page, "Планы");
      await expect(page.getByTestId("plan-week-progress")).toContainText("Текущая неделя · 1 из 3");
      const bar = page.getByTestId("plan-week-progressbar");
      await expect(bar).toHaveAttribute("aria-valuenow", "1");
      await expect(bar).toHaveAttribute("aria-valuemax", "3");
      await expect(bar).toHaveAttribute("data-percent", "33");
      const widths = await bar.evaluate((el) => ({
        track: el.getBoundingClientRect().width, fill: (el.firstElementChild as HTMLElement).getBoundingClientRect().width,
      }));
      expect(widths.fill / widths.track).toBeCloseTo(0.33, 1);
      await expectNoHorizontalOverflow(page, "Планы: прогресс недели");

      // прошлая неделя: строки без «⋯» и «Начать» (read-only), полоса 100%
      await page.getByRole("button", { name: "Предыдущая неделя" }).click();
      await expect(page.getByTestId("plan-week-progressbar")).toHaveAttribute("data-percent", "100");
      await expect(page.getByTestId("plans-row-more")).toHaveCount(0);
      await expect(page.getByTestId("plans-today")).toHaveCount(0);

      expect(consoleErrors).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
