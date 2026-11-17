import { expect, test } from "@playwright/test";

import { projectLaunchUrl } from "../fixtures/projectLaunch";

// Pure launch-contract checks: no browser, credentials, network, SDK or API replacement.
for (const version of ["8.0", "6.1"] as const) {
  test(`launch platform matches the configured browser profile (Telegram ${version})`, async ({}, testInfo) => {
    const expected = testInfo.project.use.defaultBrowserType === "webkit" ? "ios" : "android";
    const url = new URL(projectLaunchUrl("https://staging.example.invalid/", "synthetic-init-data", testInfo.project.name, version));
    const params = new URLSearchParams(url.hash.slice(1));
    expect(params.get("tgWebAppPlatform")).toBe(expected);
    expect(params.get("tgWebAppVersion")).toBe(version);
    expect(params.get("tgWebAppData")).toBe("synthetic-init-data");
  });
}

test("signup launch defaults to Telegram 8.0 for the current browser profile", async ({}, testInfo) => {
  const url = new URL(projectLaunchUrl("https://staging.example.invalid", "synthetic-init-data", testInfo.project.name));
  const params = new URLSearchParams(url.hash.slice(1));
  expect(params.get("tgWebAppVersion")).toBe("8.0");
  expect(params.get("tgWebAppPlatform")).toBe(testInfo.project.use.defaultBrowserType === "webkit" ? "ios" : "android");
});

test("unsupported project cannot silently inherit iOS launch parameters", () => {
  expect(() => projectLaunchUrl("https://staging.example.invalid", "synthetic-init-data", "unknown-project")).toThrow("Unsupported staging browser project");
});
