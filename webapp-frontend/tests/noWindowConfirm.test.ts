import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

// Аудит staging 6475bc0 (H1): в iframe Telegram Web window.confirm не показывается и сразу возвращает false —
// удаление в журнале и тестах молча не срабатывало. Подтверждения идут только через confirmAction
// (telegramPlatform.ts: WebApp.showConfirm, а window.confirm — лишь запасной путь вне Telegram).
function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(join(dir, e.name)) : [join(dir, e.name)],
  );
}

test("window.confirm вызывается только внутри confirmAction (telegramPlatform.ts)", () => {
  const root = fileURLToPath(new URL("../src", import.meta.url));
  const offenders: string[] = [];
  for (const file of walk(root).filter((f) => /\.tsx?$/.test(f))) {
    const name = relative(root, file);
    if (name === "telegramPlatform.ts") {
      continue;
    }
    readFileSync(file, "utf8").split("\n").forEach((line, index) => {
      if (/\b(window|globalThis|self)\.confirm\s*\(/.test(line.replace(/\/\/.*$/, ""))) {
        offenders.push(`${name}:${index + 1}: ${line.trim()}`);
      }
    });
  }
  assert.deepEqual(offenders, []);
});
