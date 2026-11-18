import { expect, test, type Page } from "@playwright/test";
import { buildInitData, launchUrl } from "../../e2e-staging/fixtures/initData";

test.describe.configure({ retries: 0 });

async function observeAudio(page: Page) {
  await page.addInitScript(() => {
    const events: number[] = [];
    Object.assign(window, { phaseAudioPeaks: events });
    const ramp = AudioParam.prototype.linearRampToValueAtTime;
    AudioParam.prototype.linearRampToValueAtTime = function (value, time) {
      events.push(value);
      return ramp.call(this, value, time);
    };
  });
}

async function saveVolume(page: Page, volume: number, cancel = false) {
  await page.getByRole("button", { name: "Профиль", exact: true }).click();
  await page.getByTestId("profile-settings").click();
  await page.getByRole("slider", { name: "Громкость звука таймера" }).fill(String(volume));
  if (cancel) {
    await page.getByTestId("settings-cancel").click();
  } else {
    const saved = page.waitForResponse((r) => r.url().endsWith("/api/timer/preferences") && r.request().method() === "PUT");
    await page.getByTestId("settings-save").click();
    expect((await (await saved).json()).sound_volume_percent).toBe(volume);
  }
}

async function openApp(page: Page, telegramId: number, v1 = false) {
  await observeAudio(page);
  if (v1) {
    await page.addInitScript(() => localStorage.setItem("pullup:live-engine-version", "1"));
  }
  const signed = buildInitData(telegramId, process.env.BOT_TOKEN!);
  await page.goto(launchUrl(test.info().project.use.baseURL!, signed, "android"));
}

async function startLive(page: Page) {
  await page.getByRole("button", { name: "Планы", exact: true }).click();
  await page.locator(".plan-week-day-group").filter({ hasText: /^Движок: подходы/ }).getByRole("button", { name: /^Начать:/ }).first().click();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
}

const positivePeaks = (page: Page) => page.evaluate(() =>
  (window as unknown as { phaseAudioPeaks: number[] }).phaseAudioPeaks.filter((value) => value > 0));

for (const [version, telegramId] of [[2, 935901], [1, 935902]]) {
  test(`saved 0% survives reload and mutes live v${version} phase cues`, async ({ page }) => {
    await openApp(page, telegramId, version === 1);
    await saveVolume(page, 0);
    await page.reload();
    await startLive(page);
    if (version === 2) {
      await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл", { timeout: 10_000 });
    } else {
      await expect(page.locator(".phase-panel-label")).toHaveText("Приготовься");
    }
    expect(await positivePeaks(page), "saved 0% must not schedule positive WebAudio gain").toEqual([]);
  });
}

test("saved 50% scales the existing cue; cancelling 0% preserves it after reload", async ({ page }) => {
  await openApp(page, 935903);
  await saveVolume(page, 50);
  await saveVolume(page, 0, true);
  await page.reload();
  await startLive(page);
  await expect.poll(() => positivePeaks(page)).not.toEqual([]);
  expect(await positivePeaks(page)).toEqual(expect.arrayContaining([0.15]));
  expect((await positivePeaks(page)).every((value) => value === 0.15)).toBe(true);
});

test("delayed preferences cannot play a default-volume cue while the server timer proceeds", async ({ page }) => {
  await openApp(page, 935904);
  await saveVolume(page, 50);
  await page.reload();
  let release!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  let fulfilled!: () => void;
  const applied = new Promise<void>((resolve) => { fulfilled = resolve; });
  await page.route("**/api/timer/preferences", async (route) => {
    const response = await route.fetch();
    await held;
    await route.fulfill({ response });
    fulfilled();
  });
  await startLive(page);
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл", { timeout: 10_000 });
  expect(await positivePeaks(page)).toEqual([]);
  release();
  await applied;
  await page.unroute("**/api/timer/preferences");
  // PREP has expired during the fetch: no late signal. A new REST deadline uses the saved volume.
  expect(await positivePeaks(page)).toEqual([]);
  await page.getByLabel("Результат подхода").fill("5");
  await page.getByTestId("engine-submit").click();
  await expect.poll(() => positivePeaks(page)).not.toEqual([]);
  expect((await positivePeaks(page)).every((value) => value === 0.15)).toBe(true);
});

test("preferences resolving after backgrounding cannot schedule a hidden phase cue", async ({ page }) => {
  await openApp(page, 935905);
  await saveVolume(page, 50);
  await page.reload();
  let release!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  let fulfilled!: () => void;
  const applied = new Promise<void>((resolve) => { fulfilled = resolve; });
  await page.route("**/api/timer/preferences", async (route) => {
    const response = await route.fetch();
    await held;
    await route.fulfill({ response });
    fulfilled();
  });
  await startLive(page);
  await expect(page.getByTestId("engine-phase")).toHaveText("Приготовься");
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  release();
  await applied;
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  expect(await positivePeaks(page), "hydration must not schedule audio in the background").toEqual([]);
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect.poll(() => positivePeaks(page)).not.toEqual([]);
  expect((await positivePeaks(page)).every((value) => value === 0.15)).toBe(true);
});
