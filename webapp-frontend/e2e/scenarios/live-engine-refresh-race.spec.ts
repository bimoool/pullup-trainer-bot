import { expect, test } from "@playwright/test";

import { buildInitData, getTestBotToken } from "../fixtures/initData";
import { openAppAs } from "../fixtures/setup";

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

test("a refresh captured before pause cannot replace its acknowledged state; a fresh read still applies", async ({ page }, testInfo) => {
  const identity = 930_630 + testInfo.retry;
  await openAppAs(page, identity);
  await page.getByRole("button", { name: "Планы", exact: true }).click();
  const group = page.locator(".plan-week-day-group").filter({ hasText: /^Движок: пауза/ });
  await group.getByRole("button", { name: /^Начать: / }).first().click();
  await page.getByRole("button", { name: "Начать", exact: true }).click();
  await page.getByTestId("engine-skip").click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл");
  await page.getByLabel("Результат подхода").fill("5");
  await page.getByTestId("engine-submit").click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых");
  await expect(page.getByTestId("engine-pending")).toHaveCount(0);

  const activeUrl = "**/api/v2/sessions/live/active";
  let captured!: () => void;
  const capture = new Promise<void>((resolve) => { captured = resolve; });
  let release!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  let first = true;
  await page.route(activeUrl, async (route) => {
    if (!first) return route.continue();
    first = false;
    const response = await route.fetch(); // Real server state, captured before the pause mutation.
    const body = await response.json();
    expect(body.session.engine.state.phase).toBe("REST");
    expect(body.session.engine.state.paused_at).toBeNull();
    captured();
    await held;
    await route.fulfill({ response });
  });
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await capture;
  await page.getByTestId("pause-toggle").click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых · пауза");
  await expect(page.getByTestId("engine-pending")).toHaveCount(0); // POST acknowledged and queue empty.
  const staleDelivered = page.waitForResponse((response) => response.url().endsWith("/api/v2/sessions/live/active"));
  release();
  await (await staleDelivered).finished();
  // Let the delivered body and React's render complete before checking for a reverted pause.
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых · пауза");

  // A genuinely newer server change from another device must still be accepted by refresh.
  const initData = buildInitData({ id: identity, firstName: "E2E" }, getTestBotToken());
  const headers = { "X-Telegram-Init-Data": initData };
  const current = await page.request.get("/api/v2/sessions/live/active", { headers });
  const session = (await current.json()).session;
  expect(session.engine.state.paused_at).not.toBeNull();
  const resumed = await page.request.post(`/api/v2/sessions/live/${session.id}/events`, {
    headers, data: { events: [{
      client_event_id: crypto.randomUUID(), type: "resume", payload: { phase_seq: session.engine.state.phase_seq },
      client_at: new Date().toISOString(),
    }] },
  });
  expect(resumed.ok()).toBe(true);
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых");

  // With no local mutation, the newest GET must win over an older in-flight GET too.
  await page.unroute(activeUrl);
  let capturedOld!: () => void;
  const oldCaptured = new Promise<void>((resolve) => { capturedOld = resolve; });
  let releaseOld!: () => void;
  const oldHeld = new Promise<void>((resolve) => { releaseOld = resolve; });
  let oldFirst = true;
  await page.route(activeUrl, async (route) => {
    if (!oldFirst) return route.continue();
    oldFirst = false;
    const response = await route.fetch();
    const body = await response.json();
    expect(body.session.engine.state.paused_at).toBeNull();
    capturedOld();
    await oldHeld;
    await route.fulfill({ response });
  });
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await oldCaptured;
  const pausedElsewhere = await page.request.post(`/api/v2/sessions/live/${session.id}/events`, {
    headers, data: { events: [{
      client_event_id: crypto.randomUUID(), type: "pause", payload: { phase_seq: session.engine.state.phase_seq },
      client_at: new Date().toISOString(),
    }] },
  });
  expect(pausedElsewhere.ok()).toBe(true);
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых · пауза");
  const oldDelivered = page.waitForResponse((response) => response.url().endsWith("/api/v2/sessions/live/active"));
  releaseOld();
  await (await oldDelivered).finished();
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых · пауза");

  // Slow overlapping polls must make progress before the newest request finishes.
  // Actual external changes produce A=running, B=paused, C=running; all three reads are held.
  await page.unroute(activeUrl);
  const gates = [false, true, false].map((paused) => {
    let captured!: () => void;
    let release!: () => void;
    return {
      paused,
      captured: new Promise<void>((resolve) => { captured = resolve; }),
      held: new Promise<void>((resolve) => { release = resolve; }),
      capture: () => captured(), release: () => release(),
    };
  });
  let read = 0;
  await page.route(activeUrl, async (route) => {
    const gate = gates[read++];
    if (!gate) return route.continue();
    const response = await route.fetch();
    const body = await response.json();
    expect(body.session.engine.state.paused_at !== null).toBe(gate.paused);
    gate.capture();
    await gate.held;
    await route.fulfill({ response });
  });
  for (const gate of gates) {
    const changed = await page.request.post(`/api/v2/sessions/live/${session.id}/events`, {
      headers, data: { events: [{
        client_event_id: crypto.randomUUID(), type: gate.paused ? "pause" : "resume",
        payload: { phase_seq: session.engine.state.phase_seq }, client_at: new Date().toISOString(),
      }] },
    });
    expect(changed.ok()).toBe(true);
    await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
    await gate.captured;
  }
  for (const index of [0, 2, 1]) {
    const delivered = page.waitForResponse((response) => response.url().endsWith("/api/v2/sessions/live/active"));
    gates[index].release();
    await (await delivered).finished();
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    // A applies while B/C are pending; after C is accepted, late B cannot rewind the screen.
    await expect(page.getByTestId("engine-phase")).toHaveText("Отдых");
  }

  // A newer failed read also supersedes older snapshots; a later successful read clears that error.
  await page.unroute(activeUrl);
  let captureErrorOld!: () => void;
  let releaseErrorOld!: () => void;
  const errorOldCaptured = new Promise<void>((resolve) => { captureErrorOld = resolve; });
  const errorOldHeld = new Promise<void>((resolve) => { releaseErrorOld = resolve; });
  let errorRead = 0;
  await page.route(activeUrl, async (route) => {
    if (errorRead++ === 0) {
      const response = await route.fetch();
      expect((await response.json()).session.engine.state.paused_at).not.toBeNull();
      captureErrorOld();
      await errorOldHeld;
      return route.fulfill({ response });
    }
    // Explicit transient network fault; preceding and following snapshots use the real API.
    return route.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"synthetic outage"}' });
  });
  const eventsUrl = `/api/v2/sessions/live/${session.id}/events`;
  const externalChange = async (type: "pause" | "resume") => {
    const changed = await page.request.post(eventsUrl, {
      headers, data: { events: [{ client_event_id: crypto.randomUUID(), type,
        payload: { phase_seq: session.engine.state.phase_seq }, client_at: new Date().toISOString() }] },
    });
    expect(changed.ok()).toBe(true);
  };
  await externalChange("pause");
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await errorOldCaptured;
  await externalChange("resume");
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await expect(page.getByTestId("engine-sync-error")).toBeVisible();
  const errorOldDelivered = page.waitForResponse((response) => response.url().endsWith("/api/v2/sessions/live/active"));
  releaseErrorOld();
  await (await errorOldDelivered).finished();
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых");
  await expect(page.getByTestId("engine-sync-error")).toBeVisible();
  await page.unroute(activeUrl);
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await expect(page.getByTestId("engine-sync-error")).toHaveCount(0);
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых");
});
