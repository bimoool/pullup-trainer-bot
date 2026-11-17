import { randomUUID } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";

import { buildInitData, getTestBotToken } from "../fixtures/initData";
import { openAppAs } from "../fixtures/setup";

// #421: a physical second press at the same coordinates can land on the next phase's action.
// Real FastAPI/Postgres, normal clocks/IndexedDB/transport; Telegram launch data alone is synthetic.
// Independent live_engine identities 930632–930641, including CI retries.
test.setTimeout(120_000);

async function start(page: Page, user: number) {
  const headers = { "X-Telegram-Init-Data": buildInitData({ id: user, firstName: "E2E" }, getTestBotToken()) };
  const exercises = await page.request.get("/api/v2/exercises", { headers });
  expect(exercises.ok()).toBe(true);
  const exercise = (await exercises.json()).exercises.find((e: { metric_type: string }) => e.metric_type === "reps");
  const created = await page.request.post("/api/v2/workouts", { headers, data: { title: `Gesture ${randomUUID()}` } });
  expect(created.ok()).toBe(true);
  const workout = await created.json();
  const added = await page.request.post(`/api/v2/workouts/${workout.id}/items`, { headers, data: {
    exercise_id: exercise.id,
    protocol: { type: "reps_sets", prescription: { source: "static", sets: 2, reps: 5 }, rest_seconds: 90 },
  } });
  expect(added.ok()).toBe(true);
  const started = await page.request.post("/api/v2/sessions/live", { headers, data: {
    workout_id: workout.id, client_session_id: randomUUID(), engine_version: 2,
  } });
  expect(started.ok()).toBe(true);
  const session = await started.json();
  const opened = await openAppAs(page, user);
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл", { timeout: 10_000 });
  await expect(page.getByLabel("Результат подхода")).toHaveValue("5");
  const sent: { type: string; client_event_id: string }[] = [];
  page.on("request", (request) => {
    if (request.url().endsWith(`/sessions/live/${session.id}/events`)) {
      sent.push(...request.postDataJSON().events);
    }
  });
  const state = async () => {
    const response = await page.request.get("/api/v2/sessions/live/active", { headers });
    expect(response.ok()).toBe(true);
    return (await response.json()).session?.engine.state;
  };
  return { headers, session, sent, state, opened };
}

async function finish(page: Page, run: Awaited<ReturnType<typeof start>>) {
  // Keyboard submission remains an independent action (click detail=0).
  await page.getByLabel("Результат подхода").press("Enter");
  await expect(page.getByTestId("engine-complete")).toBeVisible();
  await expect(page.getByTestId("engine-pending")).toHaveCount(0);
  const history = await page.request.get("/api/v2/sessions?status=completed&limit=200", { headers: run.headers });
  expect(history.ok()).toBe(true);
  const saved = (await history.json()).sessions.filter((s: { id: number }) => s.id === run.session.id);
  expect(saved).toHaveLength(1);
  expect(saved[0].blocks[0].set_logs.map((log: { value: string }) => Number(log.value))).toEqual([5, 5]);
  expect(run.sent.filter((event) => event.type === "submit_result")).toHaveLength(2);
  expect(new Set(run.sent.map((event) => event.client_event_id)).size).toBe(run.sent.length);
  expect(run.opened.apiFailures).toEqual([]);
}

for (const [viewIndex, viewport] of [{ width: 390, height: 844 }, { width: 390, height: 640 }].entries()) {
  test.describe(`${viewport.width}×${viewport.height}`, () => {
    test.use({ viewport, isMobile: viewIndex === 0, hasTouch: true });
    for (const [gestureIndex, gesture] of ["mouse double click", "touch double tap"].entries()) {
      test(`${gesture} logs once and keeps REST; later intentional skip works`, async ({ page }, info) => {
        const run = await start(page, 930_632 + viewIndex * 4 + gestureIndex * 2 + info.retry);
        await page.evaluate(() => {
          const trace: unknown[] = [];
          (window as unknown as { gestureTrace: unknown[] }).gestureTrace = trace;
          for (const type of ["pointerdown", "click"]) document.addEventListener(type, (event) => {
            const mouse = event as MouseEvent;
            const button = (event.target as Element).closest("button");
            const rect = (id: string) => document.querySelector(`[data-testid="${id}"]`)?.getBoundingClientRect().toJSON();
            trace.push({ type, time: performance.now(), detail: mouse.detail, x: mouse.clientX, y: mouse.clientY,
              target: button?.dataset.testid, phase: document.querySelector(".live-screen")?.getAttribute("data-engine-phase"),
              fieldFocused: document.querySelector(".live-screen")?.getAttribute("data-field-focus"), scrollY,
              submit: rect("engine-submit"), skip: rect("engine-skip") });
          }, true);
        });
        const box = (await page.getByTestId("engine-submit").boundingBox())!;
        const x = box.x + box.width / 2, y = box.y + box.height / 2;
        if (gesture === "mouse double click") {
          await page.mouse.dblclick(x, y, { delay: 100 });
        } else {
          await page.touchscreen.tap(x, y);
          await page.waitForTimeout(150); // second physical tap, no locator retargeting
          await page.touchscreen.tap(x, y);
        }
        // pending=0 also exists before the first IndexedDB commit: first prove server acknowledgement.
        await expect.poll(async () => (await run.state())?.logs.length).toBe(1);
        await expect(page.getByTestId("engine-pending")).toHaveCount(0);
        const trace = await page.evaluate(() => (window as unknown as { gestureTrace: unknown[] }).gestureTrace);
        await info.attach("physical-gesture.json", { body: JSON.stringify({ box, trace, sent: run.sent }, null, 2), contentType: "application/json" });
        expect(trace).toEqual(expect.arrayContaining([
          expect.objectContaining({ type: "click", detail: 2, target: "engine-skip", phase: "REST" }),
        ])); // the real second activation reached the replacement control
        expect(run.sent.map((event) => event.type)).toEqual(["submit_result"]);
        const resting = await run.state();
        expect(resting.phase).toBe("REST");
        expect(resting.phase_duration_ms).toBe(90_000);
        expect(resting.logs.map((log: { value: number }) => log.value)).toEqual([5]);
        await page.waitForTimeout(700); // independent gesture after the double-click sequence
        await page.getByTestId("engine-skip").click();
        await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл");
        await expect(page.getByTestId("engine-pending")).toHaveCount(0);
        expect(run.sent.filter((event) => event.type === "skip_wait")).toHaveLength(1);
        await finish(page, run);
      });
    }
  });
}

test("single activation keeps 90s REST through pause/reload and advances naturally", async ({ page }, info) => {
  const run = await start(page, 930_640 + info.retry);
  await page.getByTestId("engine-submit").click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых");
  await expect(page.getByTestId("engine-pending")).toHaveCount(0);
  expect((await run.state()).phase_duration_ms).toBe(90_000);
  await page.getByTestId("pause-toggle").click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых · пауза");
  await expect(page.getByTestId("engine-pending")).toHaveCount(0);
  const paused = await run.state();
  expect(paused.paused_remaining_ms).toBeGreaterThan(0);
  expect(paused.paused_remaining_ms).toBeLessThanOrEqual(90_000);
  await page.reload();
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых · пауза");
  expect((await run.state()).paused_remaining_ms).toBe(paused.paused_remaining_ms);
  await page.getByTestId("pause-toggle").click();
  await expect(page.getByTestId("engine-phase")).toHaveText("Отдых");
  await expect(page.getByTestId("engine-phase")).toHaveText("Пошёл", { timeout: 100_000 });
  expect(run.sent.filter((event) => event.type === "skip_wait")).toEqual([]);
  await finish(page, run);
});
