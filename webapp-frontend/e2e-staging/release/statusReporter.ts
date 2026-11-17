import { mkdirSync, writeFileSync } from "node:fs";
import type { FullResult, Reporter, TestCase, TestResult } from "@playwright/test/reporter";

const FILES = ["06-release-v2.spec.ts", "07-minimal-signup.spec.ts"] as const;
const PROJECTS = ["iphone-webkit", "chromium-mobile"] as const;
const STATUSES = ["passed", "failed", "timedOut", "skipped", "interrupted"] as const;
const MATCHERS = ["toHaveText", "toContainText", "toHaveCount", "toBeVisible", "toHaveValue", "toEqual", "toMatchObject", "toBe"] as const;
const TESTS: Record<string, string> = {
  "R-V2 fresh: full course, pause/reload, journal and rest gate persist": "fresh-course",
  "R-V2 aged qa_aged_active: current plan survives reload and fresh launch": "aged-current",
  "R-V2 aged qa_aged_legacy_snapshot: current plan survives reload and fresh launch": "aged-legacy",
  "R-V2 incident B: 10x5 keeps one-minute rests, then +10 kg survives reload": "weighted-b",
  "R-V2 incident B browser fallback 6.1: cancel preserves set; confirm ends block": "weighted-b-stop",
  "R-V2 minimal signup: optional demographics, no body fields, profile survives reload": "minimal-signup",
};

type Location = { file?: string; line?: number; column?: number };
type DiagnosticTest = Location & { title: string; project: string };
type DiagnosticError = { message?: string; stack?: string; location?: Location; snippet?: string };
type DiagnosticResult = { status: string; errors: DiagnosticError[] };

function source(location?: Location) {
  const file = FILES.find((name) => location?.file === name || location?.file?.endsWith(`/${name}`)) ?? "unknown";
  const value = location?.line;
  const line = file !== "unknown" && Number.isInteger(value) && value! > 0 && value! <= 10_000 ? value! : null;
  return { file, line };
}

/** Construct output afresh. Never copy arbitrary titles, paths, error text, values, attachments or credentials. */
export function diagnosticRecord(test: DiagnosticTest, result: DiagnosticResult) {
  return {
    schema: 1,
    test: Object.hasOwn(TESTS, test.title) ? TESTS[test.title] : "unknown",
    project: PROJECTS.find((project) => project === test.project) ?? "unknown",
    status: STATUSES.find((status) => status === result.status) ?? "unknown",
    ...source(test),
    failures: result.errors.slice(0, 3).map((error) => {
      // Playwright location is preferred. Stack fallback emits only a fixed basename and bounded integer.
      const frame = error.stack?.match(/\/(06-release-v2|07-minimal-signup)\.spec\.ts:(\d{1,5}):\d+/);
      const location = error.location ?? (frame ? { file: `${frame[1]}.spec.ts`, line: Number(frame[2]) } : undefined);
      const matcher = MATCHERS.find((name) => error.message?.includes(`.${name}(`)) ?? "unknown";
      return { ...source(location), matcher };
    }),
  };
}

export default class StatusReporter implements Reporter {
  private records: ReturnType<typeof diagnosticRecord>[] = [];

  onTestEnd(test: TestCase, result: TestResult) {
    if (this.records.length >= 20) return;
    this.records.push(diagnosticRecord({
      title: test.title, project: test.parent.project()?.name ?? "", ...test.location,
    }, result));
  }

  onEnd(result: FullResult) {
    mkdirSync("test-results", { recursive: true });
    const status = ["passed", "failed", "timedout", "interrupted"].find((value) => value === result.status) ?? "unknown";
    writeFileSync("test-results/release-status.json", JSON.stringify({ schema: 1, status, tests: this.records }));
  }
}
