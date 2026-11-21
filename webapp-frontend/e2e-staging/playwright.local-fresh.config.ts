import base from "./playwright.config";

// Isolated synthetic diagnosis only; this is never staging/release acceptance.
if (process.env.STAGING_URL !== "http://127.0.0.1:8001" || process.env.STAGING_BOT_TOKEN !== "ci-test-token") {
  throw new Error("local fresh diagnosis requires the fixed loopback URL and synthetic token");
}

export default {
  ...base,
  metadata: { ...base.metadata, verifyFreshRestDeadline: true, verifyAgedRestPersistence: true },
  testMatch: "**/06-release-v2.spec.ts",
  grep: /R-V2 (?:fresh: full course, pause\/reload, journal and rest gate persist|aged qa_aged_(?:active|legacy_snapshot): current plan survives reload and fresh launch)$/,
  projects: base.projects?.filter((project) => project.name === "iphone-webkit"),
};
