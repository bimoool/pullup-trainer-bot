import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { categoryInkVar } from "../src/homeDiscovery.ts";
import { PALETTES } from "../src/theme.ts";

// ---------- контраст токенов «Планов» (#288): WCAG AA для текста ----------
const shellCss = readFileSync(new URL("../src/shell.css", import.meta.url), "utf8");

type Rgb = [number, number, number];
const rgb = (hex: string): Rgb => {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim());
  assert.ok(m, `ожидался #rrggbb, получено «${hex}»`);
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
/** Смесь в sRGB, как color-mix(in srgb, a share%, b). */
const mix = (a: Rgb, b: Rgb, shareA: number): Rgb => [0, 1, 2].map((i) => a[i] * shareA + b[i] * (1 - shareA)) as Rgb;
const lin = (c: number) => ((c /= 255) <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const lum = ([r, g, b]: Rgb) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
const ratio = (a: Rgb, b: Rgb) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

/** Тело правила, начинающегося с `selector {` (первое вхождение). */
function block(selector: string): string {
  const start = shellCss.indexOf(`${selector} {`);
  assert.ok(start >= 0, `нет правила ${selector}`);
  return shellCss.slice(start, shellCss.indexOf("\n}", start));
}
const hexToken = (body: string, name: string): Rgb | null => {
  const m = new RegExp(`${name}:\\s*(#[0-9a-f]{6})`, "i").exec(body);
  return m === null ? null : rgb(m[1]);
};
/** Доля основного цвета в `--name: color-mix(in srgb, var(--base) P%, var(--tg-text-color))`. */
const inkShare = (body: string, name: string, base: string): number => {
  const m = new RegExp(`${name}:\\s*color-mix\\(in srgb,\\s*var\\(${base}\\)\\s*(\\d+)%,\\s*var\\(--tg-text-color\\)\\)`).exec(body);
  assert.ok(m, `нет ${name}: color-mix(... ${base} P%, текст)`);
  return Number(m[1]) / 100;
};

// Поверхности — как в приложении: светлая — белая карточка на сером; тёмная — карточка secondary_bg на bg (theme.ts).
const SCHEMES = [
  {
    name: "light", body: block(":root"), dark: false,
    card: rgb(PALETTES.light["section-bg-color"]), page: rgb(PALETTES.light["secondary-bg-color"]),
    text: rgb(PALETTES.light["text-color"]), accent: rgb(PALETTES.light["button-color"]),
  },
  {
    name: "dark", body: `${block(":root")}\n${block(':root[data-vp-scheme="dark"]')}`, dark: true,
    card: rgb(PALETTES.dark["secondary-bg-color"]), page: rgb(PALETTES.dark["bg-color"]),
    text: rgb(PALETTES.dark["text-color"]), accent: rgb(PALETTES.dark["button-color"]),
  },
];

/** Значения тёмной темы перекрывают светлые (порядок в SCHEMES: dark = root + dark-блок). */
const lastHex = (body: string, name: string): Rgb => {
  const all = [...body.matchAll(new RegExp(`${name}:\\s*(#[0-9a-f]{6})`, "gi"))];
  assert.ok(all.length > 0, `нет ${name}`);
  return rgb(all[all.length - 1][1]);
};
const lastShare = (body: string, name: string, base: string): number => {
  const all = [...body.matchAll(new RegExp(`${name}:\\s*color-mix\\(in srgb,\\s*var\\(${base}\\)\\s*(\\d+)%`, "g"))];
  assert.ok(all.length > 0, `нет ${name}`);
  return Number(all[all.length - 1][1]) / 100;
};

for (const scheme of SCHEMES) {
  test(`контраст ${scheme.name}: --vp-danger ≥ 4.5 на карточке и странице и не равен цвету категории «красная»`, () => {
    const danger = lastHex(scheme.body, "--vp-danger");
    assert.ok(ratio(danger, scheme.card) >= 4.5, `на карточке: ${ratio(danger, scheme.card).toFixed(2)}`);
    assert.ok(ratio(danger, scheme.page) >= 4.5, `на странице: ${ratio(danger, scheme.page).toFixed(2)}`);
    assert.notDeepEqual(danger, lastHex(scheme.body, "--vp-cat-1"));
  });

  for (let index = 0; index < 6; index += 1) {
    test(`контраст ${scheme.name}: текст чипа в цвете категории ${index} (--vp-cat-${index}-ink) ≥ 4.5`, () => {
      const cat = lastHex(scheme.body, `--vp-cat-${index}`);
      const ink = mix(cat, scheme.text, lastShare(scheme.body, `--vp-cat-${index}-ink`, `--vp-cat-${index}`));
      const chip = mix(cat, scheme.card, 0.16); // .plans-row-chip: 16 % категории на карточке
      const chipOnPage = mix(cat, scheme.page, 0.16);
      assert.ok(ratio(ink, chip) >= 4.5, `чип на карточке: ${ratio(ink, chip).toFixed(2)}`);
      assert.ok(ratio(ink, chipOnPage) >= 4.5, `чип на странице: ${ratio(ink, chipOnPage).toFixed(2)}`);
      if (index === 3) {
        const done = mix(cat, scheme.card, 0.18); // чип «сделано» — 18 % зелёного
        assert.ok(ratio(ink, done) >= 4.5, `чип «сделано»: ${ratio(ink, done).toFixed(2)}`);
      }
    });
  }

  test(`контраст ${scheme.name}: цвет категории как полоса/заливка ≥ 3 на карточке (тёмная --vp-cat-5 не тонет)`, () => {
    for (let index = 0; index < 6; index += 1) {
      const cat = lastHex(scheme.body, `--vp-cat-${index}`);
      if (scheme.dark) {
        assert.ok(ratio(cat, scheme.card) >= 3, `--vp-cat-${index}: ${ratio(cat, scheme.card).toFixed(2)}`);
      }
    }
  });

  test(`контраст ${scheme.name}: акцент как текст («Начать», чип ручной строки) ≥ 4.5`, () => {
    const ink = mix(scheme.accent, scheme.text, lastShare(scheme.body, "--vp-accent-ink", "--vp-accent"));
    assert.ok(ratio(ink, mix(scheme.accent, scheme.card, 0.14)) >= 4.5, "«Начать» на accent-soft 14 %");
    assert.ok(ratio(ink, mix(scheme.accent, scheme.card, 0.16)) >= 4.5, "чип на 16 %");
  });
}

test("светлые значения --vp-cat-* не менялись (на них держатся Главная и Аналитика)", () => {
  const light = block(":root");
  const expected = ["#2f80ed", "#e5484d", "#f08c1a", "#2fa56a", "#8e5bd1", "#1f3a68"];
  expected.forEach((hex, index) => assert.deepEqual(hexToken(light, `--vp-cat-${index}`), rgb(hex)));
});

test("categoryInkVar: var(--vp-cat-N) → var(--vp-cat-N-ink)", () => {
  assert.equal(categoryInkVar("var(--vp-cat-3)"), "var(--vp-cat-3-ink)");
  assert.equal(categoryInkVar("var(--vp-cat-0)"), "var(--vp-cat-0-ink)");
});

test("inkShare: формула токена читается из CSS (охрана от рассинхрона теста и стилей)", () => {
  assert.equal(inkShare(block(":root"), "--vp-cat-2-ink", "--vp-cat-2"), 0.55);
});
