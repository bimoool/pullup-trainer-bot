import * as fs from "node:fs";
import * as path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { expectA11yClean } from "../../fixtures/a11y";
import { clickAndSync } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, openTab, WIDTHS } from "../../fixtures/parity";
import { openAppAs, useLiveEngineV1 } from "../../fixtures/setup";
import { isTelegramBackButtonVisible, pressTelegramBackButton, type TelegramTheme } from "../../fixtures/telegramMock";

// issue #306: сценарий экрана движка v1 (сессии engine_version = 1) — новые старты здесь на v1.
useLiveEngineV1(test);

// #290 follow-up (a11y2): Home «Все ›» ≥44, Workout Detail назад/сердце 44, дни «Добавить в план» ≥44 без переполнения,
// «+»-шторка Главной и шторка метрик Аналитики (aria-modal, фокус внутрь, Tab-ловушка, Escape/BackButton, возврат фокуса),
// Аналитика: select/«Показать все» 44px и подписи графика ≥ 11px, контраст белого текста на обложках Главной (по пикселям
// градиента), «Показать все» скрыт у пустого пользователя, Live: открытая панель оценки видна над транспортом, без эмодзи.
// Сиды (только чтение): 997701 builder, 997702 home discovery, 999301/999311 аналитика с данными, 999901..04 пустые;
// Live — 998821/23/25/27 (session_recovery, + retry).
const THEMES: TelegramTheme[] = ["light", "dark"];
const LIVE_BASE = { 320: { light: 998_821, dark: 998_823 }, 390: { light: 998_825, dark: 998_827 } } as const;
const EMPTY = { 320: { light: 999_901, dark: 999_902 }, 390: { light: 999_903, dark: 999_904 } } as const;
const DIST = { 320: 999_301, 390: 999_311 } as const;

async function fresh(page: Page, id: number, theme: TelegramTheme, backButton = false) {
  await page.goto("about:blank");
  return openAppAs(page, id, { theme, backButton });
}

/** Контракт модальной шторки: aria-modal, фокус внутри, Tab не уходит, Escape закрывает и возвращает фокус, BackButton закрывает. */
async function expectModalContract(page: Page, opener: ReturnType<Page["locator"]>, dialogName: string | RegExp) {
  await opener.focus();
  await opener.click();
  const dialog = page.getByRole("dialog", { name: dialogName });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("aria-modal", "true");
  await expect.poll(() => dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate((el) => el.contains(document.activeElement)), `Tab ${i + 1} вышел за шторку`).toBe(true);
  }
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press("Shift+Tab");
    expect(await dialog.evaluate((el) => el.contains(document.activeElement)), `Shift+Tab ${i + 1} вышел за шторку`).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
  // Telegram BackButton закрывает шторку
  await opener.click();
  await expect(dialog).toBeVisible();
  expect(await isTelegramBackButtonVisible(page)).toBe(true);
  await pressTelegramBackButton(page);
  await expect(dialog).toHaveCount(0);
}

/** Худший контраст белого текста обложки: рисуем карточку без текста, берём самый светлый пиксель под строкой текста. */
async function worstCoverContrast(page: Page, catIndex: number): Promise<{ title: number; meta: number }> {
  const card = page.locator('[data-testid="program-row"] .home-program-card').first();
  await card.evaluate((el, i) => {
    (el as HTMLElement).style.setProperty("--cat", `var(--vp-cat-${i})`);
  }, catIndex);
  const probe = await card.evaluate((el) => {
    const rect = el.getBoundingClientRect();
    const rel = (sel: string) => {
      const t = el.querySelector(sel);
      if (!t) return null;
      const r = t.getBoundingClientRect();
      return { x: r.x - rect.x, y: r.y - rect.y, w: r.width, h: r.height, color: getComputedStyle(t).color };
    };
    return { title: rel(".home-card-title"), meta: rel(".home-card-meta") };
  });
  const style = await page.addStyleTag({ content: '.home-program-card * { color: transparent !important; text-shadow: none !important; }' });
  const png = await card.screenshot({ animations: "disabled" });
  await style.evaluate((node) => node.remove());
  return page.evaluate(async ({ b64, probe: pr }) => {
    const img = new Image();
    img.src = `data:image/png;base64,${b64}`;
    await img.decode();
    const canvas = document.createElement("canvas");
    canvas.width = img.width;
    canvas.height = img.height;
    const ctx = canvas.getContext("2d")!;
    ctx.drawImage(img, 0, 0);
    const scale = img.width / (document.querySelector('[data-testid="program-row"] .home-program-card') as HTMLElement).getBoundingClientRect().width;
    const lin = (v: number) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    const lum = (r: number, g: number, b: number) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
    const worst = (box: { x: number; y: number; w: number; h: number; color: string } | null) => {
      if (!box) return 99;
      const m = box.color.match(/rgba?\(([^)]+)\)/)!;
      const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
      const alpha = p[3] ?? 1;
      const data = ctx.getImageData(Math.floor(box.x * scale), Math.floor(box.y * scale), Math.max(1, Math.ceil(box.w * scale)), Math.max(1, Math.ceil(box.h * scale))).data;
      let min = 99;
      for (let i = 0; i < data.length; i += 4) {
        const bg = [data[i], data[i + 1], data[i + 2]];
        const fg = [0, 1, 2].map((k) => p[k] * alpha + bg[k] * (1 - alpha));
        const l1 = lum(fg[0], fg[1], fg[2]);
        const l2 = lum(bg[0], bg[1], bg[2]);
        min = Math.min(min, (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05));
      }
      return min;
    };
    return { title: worst(pr.title), meta: worst(pr.meta) };
  }, { b64: png.toString("base64"), probe });
}

for (const width of WIDTHS) {
  for (const theme of THEMES) {
    test.describe(`A11y follow-up @${width}px ${theme}`, () => {
      test.use({ viewport: { width, height: width === 320 ? 640 : 844 } });
      test.setTimeout(120_000);

      test("Главная: «Все ›» ≥ 44px, «+»-шторка — модальный диалог, обложки AA на всех цветах категорий", async ({ page }) => {
        await fresh(page, 997_702, theme, true);
        await expect(page.getByTestId("program-category").first()).toBeVisible();
        const alls = page.getByTestId("program-category-all");
        expect(await alls.count()).toBeGreaterThan(0);
        for (let i = 0; i < (await alls.count()); i++) {
          const box = (await alls.nth(i).boundingBox())!;
          expect(box.height, `«Все ›» ${i} высота`).toBeGreaterThanOrEqual(43.5);
          expect(box.width, `«Все ›» ${i} ширина`).toBeGreaterThanOrEqual(43.5);
        }
        await expectNoHorizontalOverflow(page, "Главная");

        for (let cat = 0; cat < 6; cat++) {
          const { title, meta } = await worstCoverContrast(page, cat);
          expect(title, `заголовок обложки, --vp-cat-${cat}`).toBeGreaterThanOrEqual(4.5);
          expect(meta, `мета обложки, --vp-cat-${cat}`).toBeGreaterThanOrEqual(4.5);
        }

        await expectModalContract(page, page.getByTestId("home-plus"), "Быстрые действия");
        await expectA11yClean(page, "Главная");
      });

      test("Деталь тренировки и «Добавить в план»: назад/сердце 44px, дни ≥ 44px без переполнения", async ({ page }) => {
        await fresh(page, 997_701, theme);
        await page.getByTestId("my-workout-card").first().click();
        const back = (await page.getByTestId("workout-detail-back").boundingBox())!;
        expect(back.width).toBeGreaterThanOrEqual(43.5);
        expect(back.height).toBeGreaterThanOrEqual(43.5);
        const heart = page.locator(".wd-hero-fav .favorite-heart");
        if ((await heart.count()) > 0) {
          const hb = (await heart.boundingBox())!;
          expect(hb.width).toBeGreaterThanOrEqual(43.5);
          expect(hb.height).toBeGreaterThanOrEqual(43.5);
        }
        await page.getByRole("button", { name: "Добавить в план" }).click();
        for (const day of ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]) {
          const chip = page.getByRole("button", { name: day, exact: true });
          await expect(chip).toBeVisible();
          const box = (await chip.boundingBox())!;
          expect(box.width, `день ${day} ширина`).toBeGreaterThanOrEqual(43.5);
          expect(box.height, `день ${day} высота`).toBeGreaterThanOrEqual(43.5);
          expect(box.x + box.width, `день ${day} в окне`).toBeLessThanOrEqual(width);
        }
        await expectNoHorizontalOverflow(page, "Добавить в план");
        await expectA11yClean(page, "Добавить в план");
      });

      test("Аналитика: select/«Показать все» 44px, подписи графика ≥ 11px, шторка метрик — диалог, пустой пользователь без «Показать все»", async ({ page }) => {
        await fresh(page, DIST[width] + (theme === "dark" ? 0 : 0), theme, true);
        await openTab(page, "Аналитика");
        await expect(page.getByTestId("analytics-metrics")).toBeVisible();
        const select = (await page.getByTestId("analytics-metric-select").boundingBox())!;
        expect(select.height).toBeGreaterThanOrEqual(43.5);
        const showAll = page.getByTestId("summary-show-all");
        await showAll.scrollIntoViewIfNeeded();
        expect((await showAll.boundingBox())!.height).toBeGreaterThanOrEqual(43.5);
        // подписи осей/значений графиков: эффективный размер (с учётом масштаба viewBox) ≥ 11px
        const sizes = await page.evaluate(() =>
          Array.from(document.querySelectorAll<SVGTextElement>(".analytics-weeks-chart text, .analytics-trend-chart text")).map((t) => {
            const svg = t.ownerSVGElement!;
            const scale = svg.getBoundingClientRect().width / svg.viewBox.baseVal.width;
            return parseFloat(t.getAttribute("font-size") ?? "0") * scale;
          }),
        );
        expect(sizes.length).toBeGreaterThan(0);
        for (const size of sizes) {
          expect(size).toBeGreaterThanOrEqual(10.9);
        }
        await expectNoHorizontalOverflow(page, "Аналитика");
        await expectModalContract(page, page.getByRole("button", { name: "Что значат метрики" }), "Что значат метрики");

        const emptyId = EMPTY[width][theme];
        await fresh(page, emptyId, theme);
        await openTab(page, "Аналитика");
        await expect(page.getByTestId("analytics-summary")).toBeVisible();
        await expect(page.getByTestId("summary-show-all")).toHaveCount(0);
      });

      test("Live: открытая панель оценки видна над липким транспортом", async ({ page }, testInfo) => {
        page.on("dialog", (dialog) => void dialog.accept());
        await fresh(page, LIVE_BASE[width][theme] + testInfo.retry, theme);
        await page.getByTestId("my-workout-card").filter({ hasText: "Тренировка восстановления" }).click();
        await page.getByRole("button", { name: "Добавить в план" }).click();
        await page.getByRole("button", { name: "Свободный пул" }).click();
        await page.getByRole("button", { name: "Добавить", exact: true }).click();
        const group = page.locator(".plan-week-day-group").filter({ hasText: /^Тренировка восстановления/ }).first();
        await group.getByRole("button", { name: /^Начать: / }).click();
        await page.getByRole("button", { name: "Начать", exact: true }).click();
        await clickAndSync(page, "Готов", "/phase/next");
        await expect(page.getByRole("heading", { name: "Пошёл", exact: true, level: 2 })).toBeVisible();
        await page.getByTestId("log-panel-toggle").click();
        const chips = page.getByTestId("set-effort");
        await expect(chips).toBeVisible();
        await expect.poll(async () => {
          const c = (await chips.boundingBox())!;
          const t = (await page.locator(".live-transport").boundingBox())!;
          const vh = page.viewportSize()!.height;
          return c.y >= 0 && c.y + c.height <= t.y + 0.5 && c.y + c.height <= vh;
        }, { message: "оценка 1–5 не перекрыта транспортом" }).toBe(true);
        await expectNoHorizontalOverflow(page, "Live");
      });
    });
  }
}

test("В интерфейсе не осталось эмодзи 🔥 ✎ 🏋️ (Plans/Live/legacy) — только SVG Icon", async () => {
  const root = path.resolve(process.cwd(), "../src");
  for (const file of ["DashboardScreen.tsx", "SessionLiveScreen.tsx", "WorkoutScreen.tsx"]) {
    const text = fs.readFileSync(path.join(root, file), "utf8");
    const code = text.split("\n").filter((line) => !/^\s*(\/\/|\/\*|\*)/.test(line)).join("\n");
    expect(code, file).not.toMatch(/🔥|✎|🏋/u);
  }
});
