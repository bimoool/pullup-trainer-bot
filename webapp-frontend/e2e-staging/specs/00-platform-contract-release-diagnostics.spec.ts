import { expect, test } from "@playwright/test";

import { diagnosticRecord } from "../release/statusReporter";

const secret = "synthetic-secret-token-initData=PRIVATE";

test("release diagnostic reports only fixed identity, status and source coordinates", () => {
  const record = diagnosticRecord({
    title: "R-V2 fresh: full course, pause/reload, journal and rest gate persist",
    project: "iphone-webkit", file: "/private/06-release-v2.spec.ts", line: 4,
  }, {
    status: "failed",
    errors: [{
      message: `expect(locator).toHaveText(expected) https://example.invalid/#${secret}`,
      stack: `Error: ${secret}\n    at /private/06-release-v2.spec.ts:45:61`,
      location: { file: "/private/06-release-v2.spec.ts", line: 45, column: 61 },
      snippet: secret,
    }],
  });
  expect(record).toEqual({
    schema: 1, test: "fresh-course", project: "iphone-webkit", status: "failed",
    file: "06-release-v2.spec.ts", line: 4,
    failures: [{ file: "06-release-v2.spec.ts", line: 45, matcher: "toHaveText" }],
  });
  expect(JSON.stringify(record)).not.toContain(secret);
});

test("unknown diagnostic fields fail closed and failure output is bounded", () => {
  const record = diagnosticRecord({ title: secret, project: secret, file: secret, line: -1 }, {
    status: secret,
    errors: Array.from({ length: 100 }, () => ({
      message: secret, stack: secret,
      location: { file: `/private/${secret}`, line: Number.MAX_SAFE_INTEGER, column: 1 },
    })),
  });
  expect(record).toEqual({
    schema: 1, test: "unknown", project: "unknown", status: "unknown",
    file: "unknown", line: null,
    failures: Array.from({ length: 3 }, () => ({ file: "unknown", line: null, matcher: "unknown" })),
  });
  expect(JSON.stringify(record)).not.toContain(secret);
});

test("stack fallback extracts source coordinates without serializing error text", () => {
  const record = diagnosticRecord({ title: secret, project: "chromium-mobile", file: "07-minimal-signup.spec.ts", line: 6 }, {
    status: "timedOut", errors: [{ message: secret, stack: `${secret}\n at /repo/07-minimal-signup.spec.ts:28:3` }],
  });
  expect(record.failures).toEqual([{ file: "07-minimal-signup.spec.ts", line: 28, matcher: "unknown" }]);
  expect(JSON.stringify(record)).not.toContain(secret);
});
