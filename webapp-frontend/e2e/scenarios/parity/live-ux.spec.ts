import { expect, test, type Locator, type Page } from "@playwright/test";

import { clickAndSync, noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, WIDTHS } from "../../fixtures/parity";
import { openAppAs, useLiveEngineV1 } from "../../fixtures/setup";
import { emitTelegramThemeChange, pressTelegramBackButton, type TelegramTheme } from "../../fixtures/telegramMock";

// issue #306: сценарий экрана движка v1 (сессии engine_version = 1) — новые старты здесь на v1.
useLiveEngineV1(test);

// Live Session UX fixes (#285 A): M1 — экранная клавиатура vs липкий транспорт и Enter в поле
// записи подхода; M2 — офлайн-завершение закрывает шторку и показывает статус; M3 — BackButton с
// открытой шторкой её закрывает (оценка/заметка остаются), Escape, фокус; L3 — themeChanged. Клавиатура = уменьшение высоты окна (как в Telegram WebView, см.
// keyboard-viewport.spec.ts). Seed: session_recovery — Workout «Тренировка восстановления»,
// reps 3 x 8, отдых 60 с; 9978xx — по пользователю на ширину × тему, на тест id + 2*индекс + retry.
const TITLE = "Тренировка восстановления";
const BASE: Record<number, Record<TelegramTheme, number>> = {
  320: { light: 997_801, dark: 997_811 },
  390: { light: 997_821, dark: 997_831 },
};
const KEYBOARD_VH = 380;
const VALUE_FIELD = /Результат|Секунды|Повторений/;

/** Старт из свободного пула «Планов» до «Приготовься». */
async function startLive(page: Page) {
  await page.getByTestId("my-workout-card").filter({ hasText: TITLE }).click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await page.getByRole("button", { name: "Свободный пул" }).click();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  const group = page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${TITLE}`) });
  await group.getByRole("button", { name: /^Начать: / }).click();
  await page.getByRole("button", { name: "Начать", exact: true }).click(); // SessionPreScreen
  await expect(page.getByRole("heading", { name: "Приготовься", exact: true, level: 2 })).toBeVisible();
}

async function startToGo(page: Page) {
  await startLive(page);
  await clickAndSync(page, "Готов", "/phase/next");
  await expect(page.getByRole("heading", { name: "Пошёл", exact: true, level: 2 })).toBeVisible();
}

async function boxOf(locator: Locator, what: string) {
  const box = await locator.boundingBox();
  expect(box, `${what}: нет геометрии`).not.toBeNull();
  return box!;
}

/** Элемент виден в окне и не перекрыт ничем (центр по elementFromPoint), без доп. прокрутки. */
async function expectVisibleUncovered(page: Page, target: Locator, what: string) {
  const box = await boxOf(target, what);
  const vh = page.viewportSize()!.height;
  expect(box.y, `${what}: выше окна`).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height, `${what}: ниже окна`).toBeLessThanOrEqual(vh);
  const hit = await target.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return top === el || el.contains(top);
  });
  expect(hit, `${what}: перекрыт другим элементом`).toBe(true);
}


/** Контраст текста и фона элемента (WCAG) в реальной раскраске страницы: цвета нормализует canvas. */
async function contrastOf(locator: Locator): Promise<number> {
  return locator.evaluate((el) => {
    const ctx = document.createElement("canvas").getContext("2d")!;
    const parse = (css: string): [number, number, number, number] => {
      ctx.fillStyle = "#000";
      ctx.fillStyle = css;
      const v = ctx.fillStyle as string;
      if (v.startsWith("#")) {
        const n = parseInt(v.slice(1), 16);
        return [(n >> 16) & 255, (n >> 8) & 255, n & 255, 1];
      }
      const rgba = /rgba\(([\d.]+), ([\d.]+), ([\d.]+), ([\d.]+)\)/.exec(v);
      if (rgba) {
        return [Number(rgba[1]), Number(rgba[2]), Number(rgba[3]), Number(rgba[4])];
      }
      // Chromium отдаёт color-mix() как color(srgb r g b [/ a]) с долями 0..1.
      const srgb = /color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: \/ ([\d.]+))?\)/.exec(v)!;
      return [Number(srgb[1]) * 255, Number(srgb[2]) * 255, Number(srgb[3]) * 255, srgb[4] === undefined ? 1 : Number(srgb[4])];
    };
    let bg: [number, number, number, number] = [255, 255, 255, 1];
    for (let node: Element | null = el; node; node = node.parentElement) {
      const c = parse(getComputedStyle(node).backgroundColor);
      if (c[3] > 0) {
        bg = c;
        break;
      }
    }
    const fg = parse(getComputedStyle(el).color);
    const lin = (x: number) => ((x /= 255) <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4);
    const lum = (c: number[]) => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
    const [hi, lo] = [lum(fg), lum(bg)].sort((a, b) => b - a);
    return (hi + 0.05) / (lo + 0.05);
  });
}

for (const width of WIDTHS) {
  for (const theme of ["light", "dark"] as TelegramTheme[]) {
    test.describe(`Live UX #285 @${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: width === 320 ? 640 : 844 } });
      test.setTimeout(120_000);

      const userFor = (index: number, retry: number) => BASE[width][theme] + 2 * index + retry;

      test("M1: поле записи при клавиатуре не закрыто транспортом, Enter записывает подход", async ({ page }, testInfo) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, userFor(0, testInfo.retry), { theme });
        await startToGo(page);
        const { height: fullHeight } = page.viewportSize()!;
        const input = page.getByLabel(VALUE_FIELD);
        const done = page.getByRole("button", { name: "Готово", exact: true });
        const transport = page.locator(".live-transport");

        // Клавиатура открылась: поле сфокусировано, окно стало ниже; браузер минимально прокручивает
        // сфокусированное поле к видимой области с учётом scroll-padding (block: "nearest" — тот же
        // алгоритм), т.е. поле оказывается у нижнего края окна — там, где был бы липкий транспорт.
        await input.focus();
        await page.setViewportSize({ width, height: KEYBOARD_VH });
        await page.evaluate(() => window.scrollTo(0, 0));
        await input.evaluate((el) => el.scrollIntoView({ block: "nearest" }));
        await expect(page.locator(".live-screen")).toHaveAttribute("data-field-focus", "true");

        await expectVisibleUncovered(page, input, "поле результата");
        const inputBox = await boxOf(input, "поле результата");
        const transportBox = await boxOf(transport, "транспорт");
        expect(
          inputBox.y + inputBox.height,
          "транспорт перекрывает поле (пересечение боксов)",
        ).toBeLessThanOrEqual(transportBox.y + 1);
        // «Готово» достижимо прокруткой и не перекрыто.
        await done.scrollIntoViewIfNeeded();
        await expectVisibleUncovered(page, done, "«Готово»");
        await expectNoHorizontalOverflow(page, "Live: поле записи с клавиатурой");
        await expect(transport).toHaveCSS("position", "static");

        // Enter/«Go» в поле — тот же защищённый обработчик, что у «Готово»: ровно один подход.
        await input.focus();
        await input.fill("8");
        const batches: string[] = [];
        page.on("request", (request) => {
          if (request.method() === "POST" && request.url().includes("/sets:batch")) {
            batches.push(request.url());
          }
        });
        const sync = page.waitForResponse((r) => r.url().includes("/sets:batch") && r.status() === 200);
        await page.keyboard.press("Enter");
        await page.keyboard.press("Enter"); // двойной Enter не создаёт второй подход
        await sync;
        await expect(page.getByRole("heading", { name: "Отдых", exact: true, level: 2 })).toBeVisible();
        expect(batches).toHaveLength(1);

        // Клавиатура закрыта: транспорт снова липнет к низу окна.
        await page.setViewportSize({ width, height: fullHeight });
        await expect(page.locator(".live-screen")).not.toHaveAttribute("data-field-focus", "true");
        await expect(transport).toHaveCSS("position", "sticky");

        // Enter в пустом поле ничего не записывает.
        await clickAndSync(page, "Пропустить отдых", "/phase/next");
        await clickAndSync(page, "Готов", "/phase/next");
        await expect(input).toHaveValue("");
        await input.focus();
        await input.press("Enter");
        await page.waitForTimeout(400);
        expect(batches).toHaveLength(1);
        await expect(page.getByRole("heading", { name: "Пошёл", exact: true, level: 2 })).toBeVisible();

        expect(noWakeLock(consoleErrors)).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("M2: офлайн «Сохранить и завершить» закрывает шторку и показывает статус завершения", async ({ page, context }, testInfo) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, userFor(1, testInfo.retry), { theme });
        await startLive(page);
        const completes: string[] = [];
        page.on("request", (request) => {
          if (request.method() === "POST" && request.url().includes("/complete")) {
            completes.push(request.url());
          }
        });

        await page.getByRole("button", { name: "Завершить", exact: true }).click();
        const review = page.getByTestId("workout-review");
        await expect(review).toBeVisible();
        await review.getByTestId("workout-effort").getByRole("button").nth(1).click();
        await review.getByRole("textbox", { name: "Заметка к тренировке" }).fill("без сети");

        await context.setOffline(true);
        await review.getByRole("button", { name: "Сохранить и завершить" }).click();

        // Шторка закрыта, статус и офлайн-баннер видны и не перекрыты; завершение не отправлено.
        await expect(review).toHaveCount(0);
        const status = page.getByTestId("finish-pending");
        await expect(status).toBeVisible();
        await expect(status).toContainText("отправится, когда появится сеть");
        await expectVisibleUncovered(page, status, "статус завершения");
        await expect(page.getByText(/Нет сети/).first()).toBeVisible();
        await expect(page.getByRole("button", { name: "Завершить", exact: true })).toHaveCount(0);
        await expect(page.getByRole("button", { name: "Готов", exact: true })).toHaveCount(0);
        await expectNoHorizontalOverflow(page, "Live: завершение в очереди");
        expect(completes).toEqual([]);

        // Сеть вернулась — очередь уходит, оценка и заметка с ней.
        const complete = page.waitForResponse((r) => r.url().includes("/complete") && r.status() === 200);
        await context.setOffline(false);
        await complete;
        await expect(page.getByText("Тренировка завершена")).toBeVisible();
        expect(completes).toHaveLength(1);

        expect(noWakeLock(consoleErrors)).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("M3: Back и Escape закрывают шторку, оценка и заметка остаются, фокус в диалоге и возвращается", async ({ page }, testInfo) => {
        const dialogs: string[] = [];
        page.on("dialog", (dialog) => {
          dialogs.push(dialog.message());
          void dialog.dismiss();
        });
        const completeBodies: string[] = [];
        page.on("request", (request) => {
          if (request.method() === "POST" && request.url().includes("/complete")) {
            completeBodies.push(request.postData() ?? "");
          }
        });
        const { consoleErrors, apiFailures } = await openAppAs(page, userFor(2, testInfo.retry), { theme, backButton: true });
        await startLive(page);
        const review = page.getByTestId("workout-review");
        const opener = page.getByRole("button", { name: "Завершить", exact: true });
        const chips = review.getByTestId("workout-effort").getByRole("button");
        const comment = review.getByRole("textbox", { name: "Заметка к тренировке" });

        // Открытие: фокус внутри шторки.
        await opener.click();
        await expect(review).toBeVisible();
        await expect(review).toBeFocused();
        await chips.nth(3).click();
        await comment.fill("тяжело, но ок");

        // Focus trap: Tab/Shift+Tab не выводят фокус из шторки.
        const focusables = await review.evaluate((el) => el.querySelectorAll("button, textarea, input, [tabindex]:not([tabindex='-1'])").length);
        for (let i = 0; i < focusables + 2; i += 1) {
          await page.keyboard.press("Tab");
          expect(await review.evaluate((el) => el.contains(document.activeElement)), `Tab #${i + 1} вышел из шторки`).toBe(true);
        }
        for (let i = 0; i < focusables + 2; i += 1) {
          await page.keyboard.press("Shift+Tab");
          expect(await review.evaluate((el) => el.contains(document.activeElement)), `Shift+Tab #${i + 1} вышел из шторки`).toBe(true);
        }

        // Escape закрывает, фокус возвращается на «Завершить», ввод сохранён.
        await page.keyboard.press("Escape");
        await expect(review).toHaveCount(0);
        await expect(opener).toBeFocused();
        await opener.click();
        await expect(chips.nth(3)).toHaveAttribute("aria-pressed", "true");
        await expect(comment).toHaveValue("тяжело, но ок");

        // Telegram BackButton с открытой шторкой: только закрывает её, без confirm и завершения.
        await pressTelegramBackButton(page);
        await expect(review).toHaveCount(0);
        await expect(page.getByRole("heading", { name: "Приготовься", exact: true, level: 2 })).toBeVisible();
        expect(dialogs).toEqual([]);
        await page.waitForTimeout(300);
        expect(completeBodies).toEqual([]);
        await expect(opener).toBeFocused();
        await opener.click();
        await expect(chips.nth(3)).toHaveAttribute("aria-pressed", "true");
        await expect(comment).toHaveValue("тяжело, но ок");

        // Тап по подложке тоже закрывает; Back без шторки по-прежнему даёт confirm (без review).
        await page.locator(".live-sheet-backdrop").click({ position: { x: 5, y: 5 } });
        await expect(review).toHaveCount(0);
        await pressTelegramBackButton(page);
        await expect.poll(() => dialogs.length).toBe(1);
        expect(dialogs[0]).toContain("Закончить сессию?");
        expect(completeBodies).toEqual([]);

        // Завершение из шторки отправляет введённые оценку и заметку.
        await opener.click();
        const complete = page.waitForResponse((r) => r.url().includes("/complete") && r.status() === 200);
        await review.getByRole("button", { name: "Сохранить и завершить" }).click();
        await complete;
        expect(completeBodies).toHaveLength(1);
        expect(JSON.parse(completeBodies[0])).toMatchObject({ effort: "4", comment: "тяжело, но ок" });
        await expect(page.getByText("Тренировка завершена")).toBeVisible();

        expect(noWakeLock(consoleErrors)).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("#286: счётчик подходов, нейтральный таймер, сводка на отдыхе, читаемое неактивное «Готово»", async ({ page }, testInfo) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, userFor(4, testInfo.retry), { theme });
        await startLive(page);

        // Крупный счётчик «1 / 3 ПОДХОД» + цель «8 ПОВТ»; строка «Подход 1/3 · Цель…» осталась (контракт).
        const counter = page.getByTestId("live-counter");
        await expect(counter).toBeVisible();
        await expect(counter).toContainText("1 / 3");
        await expect(counter).toContainText("Подход");
        await expect(counter).toContainText("8");
        await expect(counter).toContainText("Повт");
        const numSize = await counter.locator(".live-counter-num").first().evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
        expect(numSize).toBeGreaterThanOrEqual(36);
        await expect(page.getByText(/Подход 1\/3 · Цель: 8 повт\./)).toBeVisible();
        await expectNoHorizontalOverflow(page, "Live: счётчик");

        // Нейтральная поверхность под таймером: тот же фон, что у карточки упражнения; плашка цветная.
        const panelBg = await page.locator(".phase-panel").evaluate((el) => getComputedStyle(el).backgroundColor);
        const cardBg = await page.getByTestId("live-now").evaluate((el) => getComputedStyle(el).backgroundColor);
        expect(panelBg).toBe(cardBg);
        const pillBg = await page.locator(".phase-panel-label").evaluate((el) => getComputedStyle(el).backgroundColor);
        expect(pillBg).not.toBe(panelBg);

        // Неактивное «Готово» (поле пустое): контраст ≥ 4.5:1.
        await clickAndSync(page, "Готов", "/phase/next");
        const done = page.getByRole("button", { name: "Готово", exact: true });
        await expect(done).toBeDisabled();
        expect(await contrastOf(done), "неактивное «Готово»").toBeGreaterThanOrEqual(4.5);
        await page.getByLabel(VALUE_FIELD).fill("8");
        await expect(done).toBeEnabled();
        await clickAndSync(page, "Готово", "/sets:batch");

        // Отдых: панель свёрнута до одной строки, не обрезана липким транспортом.
        await expect(page.getByRole("heading", { name: "Отдых", exact: true, level: 2 })).toBeVisible();
        const panel = page.getByTestId("log-panel");
        await expect(panel).toHaveAttribute("data-state", "collapsed");
        await expect(page.getByTestId("log-panel-summary")).toContainText("Подход 1: 8 повт.");
        await expect(page.getByTestId("set-effort")).toHaveCount(0);
        const panelBox = await boxOf(panel, "панель отдыха");
        const transportBox = await boxOf(page.locator(".live-transport"), "транспорт");
        expect(panelBox.y + panelBox.height, "панель под транспортом").toBeLessThanOrEqual(transportBox.y + 1);
        await expectNoHorizontalOverflow(page, "Live: отдых, сводка");
        await page.getByTestId("log-panel-toggle").click();
        await expect(panel).toHaveAttribute("data-state", "expanded");
        await page.getByTestId("log-panel-toggle").click();
        await expect(panel).toHaveAttribute("data-state", "collapsed");

        expect(noWakeLock(consoleErrors)).toEqual([]);
        expect(apiFailures).toEqual([]);
      });

      test("L3: themeChanged Telegram перекрашивает приложение (переменные, схема, appearance tgui)", async ({ page }, testInfo) => {
        const { consoleErrors, apiFailures } = await openAppAs(page, userFor(3, testInfo.retry), { theme });
        await expect(page.getByTestId("my-workout-card").first()).toBeVisible();
        const root = page.locator("html");
        const appRootClass = () => page.locator("#root > div").first().getAttribute("class");
        const bg = () => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--tg-bg-color").trim());

        const other: TelegramTheme = theme === "light" ? "dark" : "light";
        await expect(root).toHaveAttribute("data-vp-scheme", theme);
        const initialBg = await bg();
        const initialClass = await appRootClass();

        await emitTelegramThemeChange(page, other);
        await expect(root).toHaveAttribute("data-vp-scheme", other);
        expect(await bg()).not.toBe(initialBg);
        expect(await appRootClass()).not.toBe(initialClass);
        await expectNoHorizontalOverflow(page, `после themeChanged → ${other}`);

        await emitTelegramThemeChange(page, theme);
        await expect(root).toHaveAttribute("data-vp-scheme", theme);
        expect(await bg()).toBe(initialBg);
        expect(await appRootClass()).toBe(initialClass);

        expect(noWakeLock(consoleErrors)).toEqual([]);
        expect(apiFailures).toEqual([]);
      });
    });
  }
}
