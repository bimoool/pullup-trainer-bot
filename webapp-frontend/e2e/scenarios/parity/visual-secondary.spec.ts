import { expect, test, type Page } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";

import { noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";
import type { TelegramTheme } from "../../fixtures/telegramMock";

// CRIMPD VISUAL (#280, tier 3): второстепенные экраны в языке оболочки (screens-secondary.css) —
// пред-экран сессии, Builder (создание/редактор/выбор упражнения/протокол), Настройки, история
// веса, «Тесты» и деталь теста (с PeerInsightsCard), Program Detail, подборка, поиск,
// «Добавить в план», «Перенести». Проверяем геометрию, не пиксели: нет горизонтального overflow,
// ровно одно главное действие (залитая акцентная кнопка) там, где оно есть, поля формы в окне.
// Seed: scripts/e2e_seed_all.sh «Visual secondary» — 9977xx, только чтение; все ширины × темы
// делят пользователей (parity-проект идёт последовательно).
//   997701 builder_workouts · 997702 home_discovery · 997703 collections · 997704 body_metrics
//   994001 peer_cohort_female (общий, только чтение; свой сид менял бы медиану когорты в peer-insights) · 997706 ready · 997707 tests_hub
// Снимки: UX_CAPTURE=1 UX_LABEL=before|after UX_CAPTURE_DIR=/tmp/ux-vis3 (тогда проверки «мягкие»).
const U = {
  builder: 997_701, home: 997_702, collections: 997_703, body: 997_704, peer: 994_001, settings: 997_706, tests: 997_707,
} as const;
const THEMES: TelegramTheme[] = ["light", "dark"];
const CAPTURE = !!process.env.UX_CAPTURE;
const check = CAPTURE ? expect.soft : expect;

async function snap(page: Page, width: number, theme: TelegramTheme, name: string) {
  if (!CAPTURE) {
    return;
  }
  const dir = path.join(process.env.UX_CAPTURE_DIR ?? "/tmp/ux-vis3", process.env.UX_LABEL ?? "after", `${width}-${theme}`);
  fs.mkdirSync(dir, { recursive: true });
  await page.waitForTimeout(250);
  await page.screenshot({ path: path.join(dir, `${name}.png`), fullPage: true });
}

/** Залитые акцентным цветом «большие» кнопки (главные CTA) вне нижней навигации. */
async function filledButtons(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const probe = document.createElement("div");
    probe.style.background = "var(--tg-button-color)";
    document.body.appendChild(probe);
    const accent = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return Array.from(document.querySelectorAll("button"))
      .filter((el) => !el.closest(".bottom-tabbar"))
      .filter((el) => {
        const r = el.getBoundingClientRect();
        return r.width >= 100 && r.height >= 36 && getComputedStyle(el).backgroundColor === accent;
      })
      .map((el) => (el.textContent ?? "").trim());
  });
}

async function verify(page: Page, where: string, opts: { primary: string | RegExp | null; width: number }) {
  await page.waitForTimeout(150);
  try {
    await expectNoHorizontalOverflow(page, where);
  } catch (error) {
    if (!CAPTURE) {
      throw error;
    }
    console.log(`[capture] ${String(error).split("\n")[0]}`);
  }
  const filled = await filledButtons(page);
  if (opts.primary === null) {
    check(filled, `«${where}»: главного залитого CTA быть не должно`).toEqual([]);
  } else {
    check(filled, `«${where}»: ровно один залитый главный CTA`).toHaveLength(1);
    const button = page.getByRole("button", { name: opts.primary, exact: typeof opts.primary === "string" }).last();
    await check(button, `«${where}»: главный CTA виден`).toBeVisible();
    const box = await button.boundingBox();
    check(box, `«${where}»: геометрия CTA`).not.toBeNull();
    if (box) {
      check(box.x, `«${where}»: CTA левее окна`).toBeGreaterThanOrEqual(0);
      check(box.x + box.width, `«${where}»: CTA шире окна`).toBeLessThanOrEqual(opts.width);
    }
  }
  // поля форм — в пределах окна (на 320 это главный риск)
  const fields = await page.evaluate(() =>
    Array.from(document.querySelectorAll("input:not([type=checkbox]):not([type=range]), select, textarea"))
      .map((el) => {
        const r = el.getBoundingClientRect();
        return { label: el.getAttribute("aria-label") ?? el.getAttribute("placeholder") ?? el.tagName, w: r.width, left: r.left, right: r.right };
      })
      .filter((f) => f.w > 0),
  );
  for (const f of fields) {
    check(f.left, `«${where}»: поле «${f.label}» левее окна`).toBeGreaterThanOrEqual(0);
    check(f.right, `«${where}»: поле «${f.label}» шире окна`).toBeLessThanOrEqual(opts.width);
  }
}

async function fresh(page: Page, id: number, theme: TelegramTheme) {
  await page.goto("about:blank");
  return openAppAs(page, id, { theme });
}

for (const width of WIDTHS) {
  for (const theme of THEMES) {
    test.describe(`Visual secondary @${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: width === 320 ? 640 : 844 } });
      test.setTimeout(150_000);

      test("Builder: создание, редактор, выбор упражнения, протокол; пред-экран сессии; «Добавить в план»; «Перенести»", async ({ page }) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, U.builder, { theme });
        await page.getByTestId("my-workouts").waitFor();

        // шаг 1: название
        await page.getByRole("button", { name: "Создать", exact: true }).click();
        await expect(page.getByRole("textbox")).toBeVisible();
        await snap(page, width, theme, "01_builder_create");
        await verify(page, "Builder: создание", { primary: "Создать и добавить упражнения", width });

        // редактор существующей тренировки
        await fresh(page, U.builder, theme);
        await page.getByTestId("my-workout-card").filter({ hasText: "Смешанная" }).click();
        await expect(page.getByTestId("workout-detail")).toBeVisible();
        await snap(page, width, theme, "02_workout_detail");

        // пред-экран сессии (свободный старт из своей тренировки) — не начинаем
        await page.getByRole("button", { name: "Начать", exact: true }).click();
        await expect(page.locator(".plan-title", { hasText: "Смешанная" })).toBeVisible();
        await snap(page, width, theme, "03_session_pre");
        await verify(page, "Пред-экран сессии", { primary: "Начать", width });
        // сводка перед стартом: состав и «подходы × повторы», главное действие и «назад» на экране
        await expect(page.getByTestId("session-pre-items").locator("li")).toHaveCount(3);
        await expect(page.getByTestId("session-pre-meta")).toContainText("3 упражнения");
        await snap(page, width, theme, "03b_session_pre_summary");
        // видимый выход без Telegram BackButton: «← Назад» уходит с пред-экрана (тот же onClose, что у BackButton)
        const back = page.getByRole("button", { name: "← Назад" });
        await expect(back).toBeVisible();
        await back.click();
        await expect(page.getByTestId("session-pre")).toHaveCount(0);
        await expect(page.getByTestId("my-workouts")).toBeVisible();

        await fresh(page, U.builder, theme);
        await page.getByTestId("my-workout-card").filter({ hasText: "Смешанная" }).click();
        await page.getByRole("button", { name: "Редактировать" }).click();
        await expect(page.getByText("Редактировать тренировку")).toBeVisible();
        await expect(page.getByTestId("workout-item").first()).toBeVisible();
        await snap(page, width, theme, "04_builder_editor");
        await verify(page, "Builder: редактор", { primary: "Сохранить", width });

        // выбор упражнения
        await page.getByRole("button", { name: /Добавить упражнение/ }).click();
        await expect(page.getByLabel("Поиск упражнения")).toBeVisible();
        await snap(page, width, theme, "05_builder_picker");
        await verify(page, "Builder: выбор упражнения", { primary: null, width });

        // протокол: повторения и интервалы
        await page.locator(".ux-pick").first().click();
        await expect(page.getByTestId("protocol-fields")).toBeVisible();
        await snap(page, width, theme, "06_protocol_reps");
        await verify(page, "Builder: протокол «Повторения»", { primary: "Добавить", width });
        await page.getByRole("radio", { name: /^Интервалы/ }).click();
        await snap(page, width, theme, "07_protocol_interval");
        await verify(page, "Builder: протокол «Интервалы»", { primary: "Добавить", width });

        // «Добавить в план»
        await fresh(page, U.builder, theme);
        await page.getByTestId("my-workout-card").filter({ hasText: "Смешанная" }).click();
        await page.getByRole("button", { name: "Добавить в план" }).click();
        await page.getByRole("button", { name: "Пн", exact: true }).click();
        await snap(page, width, theme, "08_add_to_plan");
        await verify(page, "Добавить в план", { primary: "Добавить", width });

        // пред-экран из Планов (manual-путь): та же сводка
        await fresh(page, U.builder, theme);
        await openTab(page, "Планы");
        const group = page.locator(".plan-week-day-group").filter({ hasText: /^Смешанная/ });
        await group.getByRole("button", { name: "Начать", exact: true }).click();
        await expect(page.getByTestId("session-pre-items").locator("li")).toHaveCount(3);
        await verify(page, "Пред-экран сессии из Планов", { primary: "Начать", width });

        // «Перенести» из Планов
        await fresh(page, U.builder, theme);
        await openTab(page, "Планы");
        await page.getByRole("button", { name: "Перенести" }).first().click();
        await expect(page.locator(".plan-title", { hasText: "Перенести" })).toBeVisible();
        await snap(page, width, theme, "09_move_plan_item");
        await verify(page, "Перенести", { primary: "Сохранить", width });

        expect(noWakeLock(consoleErrors)).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("Настройки и история веса", async ({ page }) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, U.settings, { theme });
        await openTab(page, "Профиль");
        await page.getByTestId("profile-settings").click();
        await expect(page.getByTestId("settings-screen")).toBeVisible();
        await snap(page, width, theme, "10_settings");
        await verify(page, "Настройки", { primary: "Сохранить", width });

        await fresh(page, U.body, theme);
        await openTab(page, "Профиль");
        await page.getByTestId("profile-weight").click();
        await expect(page.getByTestId("body-metrics-screen")).toBeVisible();
        await snap(page, width, theme, "11_body_metrics");
        await verify(page, "История веса", { primary: /Добавить замер/u, width });
        await page.getByTestId("body-metrics-add").click();
        await expect(page.getByTestId("body-metrics-form")).toBeVisible();
        await snap(page, width, theme, "12_body_metrics_form");
        await verify(page, "История веса: форма замера", { primary: "Сохранить", width });

        expect(noWakeLock(consoleErrors)).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("Тесты, деталь теста с «Сравнением с похожими»", async ({ page }) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, U.tests, { theme });
        await page.getByTestId("home-tests-row").click();
        await expect(page.getByTestId("tests-screen")).toBeVisible();
        await expect(page.getByTestId("test-card").first()).toBeVisible();
        await snap(page, width, theme, "13_tests_hub");
        await verify(page, "Тесты", { primary: null, width });

        await page.getByTestId("test-card").filter({ hasText: "Максимум подтягиваний" }).click();
        await expect(page.getByTestId("test-detail")).toBeVisible();
        await expect(page.getByTestId("peer-insights")).toBeVisible();
        await snap(page, width, theme, "14_test_detail");
        await verify(page, "Деталь теста", { primary: "Записать результат", width });

        await fresh(page, U.peer, theme);
        await page.getByTestId("home-tests-row").click();
        await page.getByTestId("test-card").filter({ hasText: "Подтягивания с весом, кг" }).click();
        await expect(page.getByTestId("peer-insights-percentile")).toBeVisible();
        await snap(page, width, theme, "15_test_detail_peers");
        await verify(page, "Деталь теста: когорта", { primary: "Записать результат", width });

        expect(noWakeLock(consoleErrors)).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("#287 LOW 5/7: «Начать» пред-экрана у низа окна (над safe area), кольцо фокуса в списке не обрезано", async ({ page }) => {
        // LOW 5: пред-экран без нижней навигации — транспорт у самого низа окна, кнопка над home indicator.
        const { consoleErrors, apiFailures } = await openAppAs(page, U.builder, {
          theme, telegram: { version: "8.0", safeAreaInset: { top: 0, bottom: 34, left: 0, right: 0 } },
        });
        await page.getByTestId("my-workout-card").filter({ hasText: "Смешанная" }).click();
        await page.getByRole("button", { name: "Начать", exact: true }).click();
        await expect(page.getByTestId("session-pre")).toBeVisible();
        const vh = page.viewportSize()!.height;
        const transport = (await page.locator(".pre-transport").boundingBox())!;
        expect(Math.round(transport.y + transport.height), "транспорт пред-экрана прижат к низу окна").toBe(vh);
        const start = (await page.getByRole("button", { name: "Начать", exact: true }).boundingBox())!;
        const gap = vh - (start.y + start.height);
        expect(gap, "«Начать» над safe area (16 + 34), а не на высоте отсутствующей навигации").toBeGreaterThanOrEqual(34);
        expect(gap).toBeLessThanOrEqual(16 + 34 + 2);
        expect(await page.evaluate(() => getComputedStyle(document.querySelector(".app-shell")!).paddingBottom)).toBe("0px");
        await expectNoHorizontalOverflow(page, "Пред-экран: safe area");

        // LOW 7: строка сгруппированного списка (overflow: hidden) с фокусом с клавиатуры — кольцо внутрь.
        await fresh(page, U.tests, theme);
        await page.getByTestId("home-tests-row").click();
        const card = page.getByTestId("test-card").first();
        await expect(card).toBeVisible();
        await page.keyboard.press("Shift"); // клавиатурная модальность → :focus-visible
        await card.focus();
        const ring = await card.evaluate((el) => {
          const style = getComputedStyle(el);
          return { visible: el.matches(":focus-visible"), style: style.outlineStyle, width: style.outlineWidth, offset: style.outlineOffset };
        });
        expect(ring).toEqual({ visible: true, style: "solid", width: "2px", offset: "-2px" });

        expect(noWakeLock(consoleErrors)).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("Program Detail, подборка, поиск", async ({ page }) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, U.home, { theme });
        await page.locator(".program-card-button").first().click();
        await expect(page.getByTestId("program-detail-title")).toBeVisible();
        await expect(page.getByTestId("program-cover")).toBeVisible();
        const chevron = (await page.getByRole("button", { name: "← Назад" }).boundingBox())!;
        expect(Math.round(chevron.width), "круглая «назад» 40 px").toBe(40);
        expect(Math.round(chevron.height)).toBe(40);
        await snap(page, width, theme, "16_program_detail");
        await verify(page, "Program Detail", { primary: "Добавить в план", width });

        await fresh(page, U.home, theme);
        await page.getByTestId("home-search-pill").click();
        await expect(page.getByTestId("search-screen")).toBeVisible();
        await expect(page.getByTestId("search-count")).toBeVisible();
        await snap(page, width, theme, "17_search");
        await verify(page, "Поиск", { primary: null, width });

        await fresh(page, U.collections, theme);
        await page.getByTestId("collection-card").first().click();
        await expect(page.getByTestId("collection-item").first()).toBeVisible();
        await expect(page.getByTestId("collection-cover")).toBeVisible();
        await snap(page, width, theme, "18_collection");
        await verify(page, "Подборка", { primary: null, width });

        expect(noWakeLock(consoleErrors)).toEqual([]);
        expect(apiFailures).toEqual([]);
      });
    });
  }
}
