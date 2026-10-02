import assert from "node:assert/strict";
import { readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

// macOS/Windows file systems are case-insensitive: two files differing only by case break
// `tsc -b` there while Linux CI stays green (#278). Keep src/ names unique ignoring case.
function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(join(dir, e.name)) : [join(dir, e.name)],
  );
}

test("no two files under src/ differ only by letter case", () => {
  const root = fileURLToPath(new URL("../src", import.meta.url));
  const seen = new Map<string, string>();
  const clashes: string[] = [];
  for (const file of walk(root)) {
    const key = file.toLowerCase();
    const prev = seen.get(key);
    if (prev) clashes.push(`${prev} <-> ${file}`);
    else seen.set(key, file);
  }
  assert.deepEqual(clashes, []);
});
