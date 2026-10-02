import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { FIELD_BLUR_GRACE_MS, isTextEntryTarget } from "../src/liveFieldFocus.ts";

test("isTextEntryTarget: поля, открывающие клавиатуру", () => {
  assert.equal(isTextEntryTarget({ tagName: "INPUT", type: "number" }), true);
  assert.equal(isTextEntryTarget({ tagName: "input", type: "text" }), true);
  assert.equal(isTextEntryTarget({ tagName: "INPUT" }), true);
  assert.equal(isTextEntryTarget({ tagName: "TEXTAREA" }), true);
});

test("isTextEntryTarget: кнопки, чекбоксы и не-поля — нет", () => {
  assert.equal(isTextEntryTarget({ tagName: "BUTTON" }), false);
  assert.equal(isTextEntryTarget({ tagName: "INPUT", type: "checkbox" }), false);
  assert.equal(isTextEntryTarget({ tagName: "INPUT", type: "submit" }), false);
  assert.equal(isTextEntryTarget({ tagName: "DIV" }), false);
  assert.equal(isTextEntryTarget(null), false);
  assert.equal(isTextEntryTarget(undefined), false);
});

test("FIELD_BLUR_GRACE_MS: достаточно для тапа по кнопке транспорта", () => {
  assert.ok(FIELD_BLUR_GRACE_MS >= 200 && FIELD_BLUR_GRACE_MS <= 1000);
});

// ---------- контраст токенов (#285): WCAG AA ----------
const CSS_DIR = new URL("../src/", import.meta.url);
const liveCss = readFileSync(new URL("live.css", CSS_DIR), "utf8");
const shellCss = readFileSync(new URL("shell.css", CSS_DIR), "utf8");

type Rgb = [number, number, number];
const rgb = (hex: string): Rgb => {
  const m = /^#([0-9a-f]{6}|[0-9a-f]{3})$/i.exec(hex.trim());
  assert.ok(m, `ожидался #rgb/#rrggbb, получено «${hex}»`);
  const n = parseInt(m[1].length === 3 ? [...m[1]].map((c) => c + c).join("") : m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const mix = (a: Rgb, b: Rgb, shareA: number): Rgb => [0, 1, 2].map((i) => a[i] * shareA + b[i] * (1 - shareA)) as Rgb;
const lin = (c: number) => ((c /= 255) <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const lum = ([r, g, b]: Rgb) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
const ratio = (a: Rgb, b: Rgb) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

/** Значения `--name: #hex` из блока правила, начинающегося с `selector {`. */
function tokens(css: string, selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  assert.ok(start >= 0, `нет правила ${selector}`);
  const body = css.slice(start, css.indexOf("}", start));
  const out: Record<string, string> = {};
  for (const m of body.matchAll(/(--[\w-]+):\s*(#[0-9a-f]{3,6})/gi)) {
    out[m[1]] = m[2];
  }
  return out;
}

// Поверхности: карточка светлой темы (section_bg #fff) и тёмной (secondary_bg #232e3c) — theme.ts PALETTES.
const SCHEMES = [
  { name: "light", card: "#ffffff", page: "#f2f2f7", vars: tokens(liveCss, ".live-screen") },
  {
    name: "dark", card: "#232e3c", page: "#17212b",
    vars: { ...tokens(liveCss, ".live-screen"), ...tokens(liveCss, ':root[data-vp-scheme="dark"] .live-screen') },
  },
];

for (const scheme of SCHEMES) {
  for (const phase of ["get_ready", "go", "rest"] as const) {
    test(`контраст ${scheme.name}: подпись фазы «${phase}» на тонировке и плашке ≥ 4.5`, () => {
      const accent = rgb(scheme.vars[`--live-${phase}`]);
      const ink = rgb(scheme.vars[`--live-${phase}-ink`]);
      const tint = mix(accent, rgb(scheme.card), 0.13); // .phase-card-*: 13 % акцента на карточке
      const pill = mix(accent, tint, 0.16); // .phase-panel-label: плашка 16 %
      assert.ok(ratio(ink, tint) >= 4.5, `${phase} на тонировке: ${ratio(ink, tint).toFixed(2)}`);
      assert.ok(ratio(ink, pill) >= 4.5, `${phase} на плашке: ${ratio(ink, pill).toFixed(2)}`);
      // и «cue» «Приготовься · N» / метка перехода блока на самой карточке
      assert.ok(ratio(ink, rgb(scheme.card)) >= 4.5);
    });
  }

  test(`контраст ${scheme.name}: галочка на заливке --live-go ≥ 3 (графика)`, () => {
    const fg = rgb(scheme.vars["--live-check-fg"]);
    const fill = rgb(scheme.vars["--live-go"]);
    assert.ok(ratio(fg, fill) >= 3, `галочка: ${ratio(fg, fill).toFixed(2)}`);
  });
}

// Мелкие подписи: --vp-hint = 60 % hint + 40 % text (shell.css) на карточке и странице.
test("контраст: --vp-hint объявлен в shell.css и применён вместо сырого hint в live.css", () => {
  assert.match(shellCss, /--vp-hint:\s*color-mix\(in srgb, var\(--tg-hint-color\) 60%, var\(--tg-text-color\)\)/);
  assert.equal(/color:\s*var\(--tg-hint-color\)/.test(liveCss), false, "в live.css остался сырой --tg-hint-color для текста");
});

for (const { name, hint, text, surfaces } of [
  { name: "light", hint: "#999999", text: "#111111", surfaces: ["#ffffff", "#f2f2f7"] },
  { name: "dark", hint: "#708499", text: "#f5f5f5", surfaces: ["#232e3c", "#17212b"] },
]) {
  test(`контраст ${name}: --vp-hint на карточке и странице ≥ 4.5`, () => {
    const mixed = mix(rgb(hint), rgb(text), 0.6);
    for (const surface of surfaces) {
      assert.ok(ratio(mixed, rgb(surface)) >= 4.5, `${surface}: ${ratio(mixed, rgb(surface)).toFixed(2)}`);
    }
  });
}
