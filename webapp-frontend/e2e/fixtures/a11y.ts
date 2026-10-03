import { expect, type Page } from "@playwright/test";

// Автоматические проверки доступности для parity-спеков (#290): цели касания ≥ 44px и контраст текста
// WCAG AA (4.5:1; 3:1 для крупного ≥ 24px / ≥ 18.66px жирного). Считаем по computed-стилям, как есть
// на экране: фон — первый непрозрачный слой предков с альфа-композицией, `color(srgb …)` от color-mix
// разбираем тоже. Выключенные (disabled) элементы пропускаем (WCAG их не требует).
export type A11yScan = { small: string[]; contrast: string[]; unnamed: string[] };

export async function scanA11y(page: Page, options: { skip?: string } = {}): Promise<A11yScan> {
  return page.evaluate((skipSelector) => {
    const parse = (c: string) => {
      const cm = c.match(/color\(srgb ([^)]+)\)/);
      if (cm) {
        const q = cm[1].split(/[ /]+/).map(Number);
        return { r: q[0] * 255, g: q[1] * 255, b: q[2] * 255, a: q[3] ?? 1 };
      }
      const m = c.match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
      return { r: p[0], g: p[1], b: p[2], a: p[3] ?? 1 };
    };
    type Rgba = { r: number; g: number; b: number; a: number };
    const lum = (c: Rgba) => {
      const f = (v: number) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
      return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
    };
    const blend = (top: Rgba, bot: Rgba): Rgba => ({
      r: top.r * top.a + bot.r * (1 - top.a), g: top.g * top.a + bot.g * (1 - top.a), b: top.b * top.a + bot.b * (1 - top.a), a: 1,
    });
    const bgOf = (el: Element) => {
      const chain: Rgba[] = [];
      let e: Element | null = el;
      while (e) {
        const c = parse(getComputedStyle(e).backgroundColor);
        if (c && c.a > 0) { chain.push(c); if (c.a >= 1) break; }
        e = e.parentElement;
      }
      let base: Rgba = { r: 255, g: 255, b: 255, a: 1 };
      for (const c of chain.reverse()) base = blend(c, base);
      return base;
    };
    const hasImageBg = (el: Element) => {
      let e: Element | null = el;
      while (e) { if (getComputedStyle(e).backgroundImage !== "none") return true; e = e.parentElement; }
      return false;
    };
    const visible = (el: Element) => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none" && s.opacity !== "0";
    };
    const skipped = (el: Element) => (skipSelector ? el.closest(skipSelector) !== null : false) || el.closest(":disabled") !== null;
    const describe = (el: Element) => `${el.tagName.toLowerCase()}[${(el.getAttribute("aria-label") || el.textContent || "").trim().slice(0, 28)}]`;
    const out = { small: [] as string[], contrast: [] as string[], unnamed: [] as string[] };
    document.querySelectorAll('button, a[href], [role="button"], [role="tab"], input, select, textarea').forEach((el) => {
      if (!visible(el) || skipped(el)) return;
      const r = el.getBoundingClientRect();
      if (r.bottom < 0 || r.top > innerHeight * 4) return;
      if (r.width < 43.5 || r.height < 43.5) out.small.push(`${describe(el)} ${Math.round(r.width)}x${Math.round(r.height)}`);
      const named = (el.getAttribute("aria-label") || (el as HTMLElement).innerText || el.getAttribute("title") || (el as HTMLInputElement).placeholder || "").trim() !== ""
        || ((el as HTMLInputElement).labels?.length ?? 0) > 0 || el.getAttribute("aria-labelledby") !== null;
      if (!named) out.unnamed.push(el.outerHTML.slice(0, 100));
    });
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const seen = new Set<Element>();
    let node: Node | null;
    while ((node = walker.nextNode())) {
      if (!node.textContent!.trim()) continue;
      const el = node.parentElement!;
      if (seen.has(el) || !visible(el) || skipped(el) || hasImageBg(el)) continue;
      seen.add(el);
      const s = getComputedStyle(el);
      const fg0 = parse(s.color);
      if (!fg0) continue;
      const bg = bgOf(el);
      const fg = blend({ ...fg0, a: fg0.a * parseFloat(s.opacity) }, bg);
      const L1 = lum(fg), L2 = lum(bg);
      const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
      const px = parseFloat(s.fontSize);
      const large = px >= 24 || (px >= 18.66 && parseInt(s.fontWeight) >= 700);
      if (ratio < (large ? 3 : 4.5)) out.contrast.push(`${ratio.toFixed(2)} ${describe(el)} ${px}px`);
    }
    return out;
  }, options.skip ?? "");
}

/** Экран без нарушений: цели ≥ 44px, контраст AA, у каждого поля/кнопки есть имя. */
export async function expectA11yClean(page: Page, where: string, options: { skip?: string; allowSmall?: RegExp } = {}) {
  await page.waitForTimeout(250);
  const scan = await scanA11y(page, options);
  const small = options.allowSmall ? scan.small.filter((item) => !options.allowSmall!.test(item)) : scan.small;
  expect(small, `цели касания < 44px на «${where}»`).toEqual([]);
  expect(scan.contrast, `контраст < AA на «${where}»`).toEqual([]);
  expect(scan.unnamed, `элементы без доступного имени на «${where}»`).toEqual([]);
}

/** Tab ×count: у каждого сфокусированного элемента есть видимый индикатор (outline или box-shadow). */
export async function expectFocusRings(page: Page, where: string, count = 12) {
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  const bad: string[] = [];
  for (let i = 0; i < count; i++) {
    await page.keyboard.press("Tab");
    const info = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const s = getComputedStyle(el);
      const outline = s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0;
      return { label: (el.getAttribute("aria-label") || el.innerText || el.tagName).trim().slice(0, 30), ok: outline || s.boxShadow !== "none" };
    });
    if (info !== null && !info.ok) bad.push(info.label);
  }
  expect(bad, `нет видимого фокуса на «${where}»`).toEqual([]);
}
