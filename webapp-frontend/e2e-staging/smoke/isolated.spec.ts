import { mkdirSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { buildInitData } from "../fixtures/initData";
import { projectLaunchUrl } from "../fixtures/projectLaunch";

test("isolated signed launch, authenticated state and navigation", async ({ page, request, baseURL }, info) => {
  const stage = (name: string) => { info.annotations.push({ type: "smoke_stage", description: name }); };
  stage("api-auth");
  const signed = buildInitData(996911, process.env.BOT_TOKEN!);
  const headers = { "X-Telegram-Init-Data": signed };
  expect((await request.get("/api/profile", { headers })).status(), "SIGNED_API_FAILED").toBe(200);
  expect((await request.get("/api/profile")).status(), "MISSING_SIGNATURE_ACCEPTED").toBe(422);
  const tampered = new URLSearchParams(signed);
  tampered.set("hash", "0".repeat(64));
  expect((await request.get("/api/profile", { headers: { "X-Telegram-Init-Data": tampered.toString() } })).status(), "TAMPERED_SIGNATURE_ACCEPTED").toBe(401);

  let pageExceptions = 0;
  let apiFailures = 0;
  let authenticatedResponses = 0;
  let providerLoaded = false;
  let providerFailed = false;
  page.on("pageerror", () => { pageExceptions += 1; });
  page.on("requestfailed", (r) => {
    if (r.url().startsWith(`${baseURL}/api/`)) apiFailures += 1;
    if (r.url().startsWith("https://telegram.org/js/telegram-web-app.js")) providerFailed = true;
  });
  page.on("response", (r) => {
    const url = new URL(r.url());
    if (url.origin === baseURL && url.pathname.startsWith("/api/")) {
      if (r.status() >= 400) apiFailures += 1;
      else authenticatedResponses += 1;
    }
    if (url.origin === "https://telegram.org" && url.pathname === "/js/telegram-web-app.js") {
      providerLoaded = r.ok();
      providerFailed = !r.ok();
    }
  });
  stage("provider");
  const homeResponse = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/v2/plan" && r.ok());
  // Keep a failed provider from leaving an unhandled response-wait promise.
  void homeResponse.catch(() => undefined);
  await page.goto(projectLaunchUrl(baseURL!, signed, info.project.name), { waitUntil: "load" });
  expect(providerLoaded && !providerFailed, "TELEGRAM_PROVIDER_UNAVAILABLE").toBe(true);
  expect(await page.evaluate(() => Boolean((window as unknown as { Telegram?: { WebApp?: unknown } }).Telegram?.WebApp)), "TELEGRAM_PROVIDER_MISSING").toBe(true);
  await expect(page.locator(".bottom-tabbar")).toBeVisible();
  await homeResponse;
  await expect(page.getByText("Свип: тренировка", { exact: true }).first()).toBeVisible();
  mkdirSync("smoke-results", { recursive: true });
  for (const [key, label, path] of [["home", "Главная", ""], ["plans", "Планы", "/api/v2/plan"], ["journal", "Журнал", "/api/v2/sessions"], ["analytics", "Аналитика", "/api/v2/analytics/training"], ["profile", "Профиль", "/api/profile"]]) {
    stage(key);
    const response = path ? page.waitForResponse((r) => new URL(r.url()).pathname === path && r.ok()) : null;
    await page.locator(".bottom-tabbar").getByRole("button", { name: label, exact: true }).click();
    if (response) await response;
    await expect(page.locator(".bottom-tabbar-item-active")).toHaveText(label);
    if (key === "home") await expect(page.getByText("Свип: тренировка", { exact: true }).first()).toBeVisible();
    if (key === "plans") await expect(page.getByTestId("plan-week-stepper").first()).toBeVisible();
    if (key === "journal") await expect(page.getByTestId("journal-card").first()).toBeVisible();
    if (key === "analytics") await expect(page.getByTestId("analytics-metrics")).toBeVisible();
    if (key === "profile") await expect(page.getByTestId("profile-weight")).toContainText("75");
    await expect(page.locator(".error-banner")).toHaveCount(0);
    // The early boot diagnostic can include location.href: never publish it.
    expect(await page.locator("body").innerText().then((text) => text.includes("tgWebAppData") || text.includes(signed)), "UNSAFE_DIAGNOSTIC_SCREEN").toBe(false);
    expect(pageExceptions, "PAGE_EXCEPTION").toBe(0);
    expect(apiFailures, "UNEXPECTED_API_FAILURE").toBe(0);
    // Only synthetic UI after successful checks; never capture diagnostic/error pages.
    await page.screenshot({ path: `smoke-results/${key}.png` });
  }
  stage("reload");
  await page.reload({ waitUntil: "load" });
  await expect(page.locator(".bottom-tabbar")).toBeVisible();
  const reloadedProfile = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/profile" && r.ok());
  await page.locator(".bottom-tabbar").getByRole("button", { name: "Профиль", exact: true }).click();
  await reloadedProfile;
  await expect(page.getByTestId("profile-weight")).toContainText("75");
  expect(authenticatedResponses, "BROWSER_AUTHENTICATED_API_MISSING").toBeGreaterThan(0);
  expect(apiFailures, "UNEXPECTED_API_FAILURE").toBe(0);
  expect(pageExceptions, "PAGE_EXCEPTION").toBe(0);
  stage("complete");
});
