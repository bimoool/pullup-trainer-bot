import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

// #287 LOW 6: подпись категории на обложке Program Detail / подборки (.vs-cover-label) — белый текст
// на градиенте категории. Модель фона под подписью (screens-secondary.css .vs-cover): градиент 135°
// между color-mix(cat 88%, #000) и color-mix(cat 62%, #0b1220), сверху белый блик до 14%, сверху —
// затемнение --vs-cover-scrim. Худший случай по всем категориям shell.css должен держать WCAG AA.
const CSS_DIR = new URL("../src/", import.meta.url);
const shellCss = readFileSync(new URL("shell.css", CSS_DIR), "utf8");
const secondaryCss = readFileSync(new URL("screens-secondary.css", CSS_DIR), "utf8");

type Rgb = [number, number, number];
const hex = (value: string): Rgb => {
  const m = /^#([0-9a-f]{6})$/i.exec(value.trim());
  assert.ok(m, `ожидался #rrggbb, получено «${value}»`);
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const mix = (a: Rgb, b: Rgb, shareA: number): Rgb => [0, 1, 2].map((i) => a[i] * shareA + b[i] * (1 - shareA)) as Rgb;
const lin = (c: number) => ((c /= 255) <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const lum = ([r, g, b]: Rgb) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
const ratio = (a: Rgb, b: Rgb) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};
const rule = (css: string, selector: string) => {
  const start = css.indexOf(`${selector} {`);
  assert.ok(start >= 0, `нет правила ${selector}`);
  return css.slice(start, css.indexOf("}", start));
};

test("обложка: подпись категории ≥ 4.5:1 на любой категории (#287 LOW 6)", () => {
  const cats = [...shellCss.matchAll(/--vp-cat-\d+:\s*(#[0-9a-f]{6})/gi)].map((m) => hex(m[1]));
  assert.ok(cats.length >= 6, "категории --vp-cat-* не найдены");
  const scrim = /--vs-cover-scrim:\s*rgba\(0,\s*0,\s*0,\s*([\d.]+)\)/.exec(rule(secondaryCss, ".vs-cover"));
  assert.ok(scrim, "нет --vs-cover-scrim в .vs-cover");
  const label = /\bcolor:\s*(#[0-9a-f]{6})/i.exec(rule(secondaryCss, ".vs-cover-label"));
  assert.ok(label, ".vs-cover-label: цвет должен быть непрозрачным #rrggbb");
  const fg = hex(label[1]);
  const alpha = Number(scrim[1]);
  const white: Rgb = [255, 255, 255];
  let worst = Infinity;
  for (const cat of cats) {
    const from = mix(cat, [0, 0, 0], 0.88);
    const to = mix(cat, hex("#0b1220"), 0.62);
    for (const t of [0, 0.2, 0.4, 0.6]) {
      for (const glare of [0, 0.07, 0.14]) {
        const bg = mix([0, 0, 0], mix(white, mix(to, from, t), glare), alpha);
        worst = Math.min(worst, ratio(fg, bg));
      }
    }
  }
  assert.ok(worst >= 4.5, `подпись обложки: ${worst.toFixed(2)}:1 < 4.5:1`);
});
