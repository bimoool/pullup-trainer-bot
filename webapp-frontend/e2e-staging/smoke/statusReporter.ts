import { mkdirSync, writeFileSync } from "node:fs";
import type { FullResult, Reporter, TestCase, TestResult } from "@playwright/test/reporter";

// Never serialize errors, URLs, request headers, console messages or test attachments.
export default class StatusReporter implements Reporter {
  private stage = "setup";
  onTestEnd(test: TestCase, _result: TestResult) {
    const allowed = ["api-auth", "provider", "home", "plans", "journal", "analytics", "profile", "reload", "complete"];
    const value = test.annotations.filter((a) => a.type === "smoke_stage").at(-1)?.description;
    if (value && allowed.includes(value)) this.stage = value;
  }
  onEnd(result: FullResult) {
    mkdirSync("smoke-results", { recursive: true });
    writeFileSync("smoke-results/status.json", JSON.stringify({ schema: 1, status: result.status, stage: this.stage }));
    console.log(`ISOLATED_SMOKE_${result.status.toUpperCase()}`);
  }
}
