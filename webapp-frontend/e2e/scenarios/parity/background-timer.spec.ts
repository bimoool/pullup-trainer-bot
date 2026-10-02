import { expect, test, type Page } from "@playwright/test";

import { clickAndSync, noWakeLock, playSets } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";

// Crimpd parity — «Background timer» (#269): фон/блокировка → возврат через границу фазы.
// Часы браузера двигаем через page.clock (серверное время при этом реальное): сначала
// «уходим в фон» (visibilityState=hidden), потом fastForward, потом «возвращаемся».
// Сиды (scripts/e2e_seed_all.sh): отдых 60 с — session_recovery 9991x1/9991x2,
// interval 180 с (работа 10 / отдых 20) — background_interval 9991x1+20/+21; +retry.
const REST_BASE = { 320: 999_101, 390: 999_111 } as const;
const INTERVAL_BASE = { 320: 999_121, 390: 999_131 } as const;
const THEMES = { 320: "light", 390: "dark" } as const;

test.setTimeout(120_000);

type Probe = {
  wakeRequests: number;
  wakeActive: number;
  beepStarts: number[];
};

/** Заглушки Wake Lock и Web Audio ДО загрузки приложения: считают захваты замка (браузер
 * снимает замок при уходе в фон — имитируем событием release) и планирование бипов
 * (задержка от «сейчас» в секундах). */
async function installProbes(page: Page) {
  await page.addInitScript(() => {
    const probe = { wakeRequests: 0, wakeActive: 0, beepStarts: [] as number[] };
    (window as unknown as { __probe: typeof probe }).__probe = probe;
    const sentinels: Array<EventTarget & { released: boolean }> = [];
    Object.defineProperty(navigator, "wakeLock", {
      configurable: true,
      value: {
        request: async () => {
          const s = Object.assign(new EventTarget(), {
            released: false,
            release() {
              if (!s.released) {
                s.released = true;
                probe.wakeActive -= 1;
                s.dispatchEvent(new Event("release"));
              }
              return Promise.resolve();
            },
          });
          sentinels.push(s);
          probe.wakeRequests += 1;
          probe.wakeActive += 1;
          return s;
        },
      },
    });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") {
        sentinels.forEach((s) => void s.release()); // ОС/браузер снимает замок в фоне
      }
    });
    const t0 = Date.now();
    class FakeAudioContext {
      state = "running";
      destination = {};
      get currentTime() { return (Date.now() - t0) / 1000; }
      resume() { return Promise.resolve(); }
      createGain() {
        return { gain: { setValueAtTime() {}, linearRampToValueAtTime() {} }, connect() {} };
      }
      createOscillator() {
        const ctx = this;
        return {
          type: "", frequency: { value: 0 }, connect() {}, stop() {},
          start(when: number) { probe.beepStarts.push(Math.round((when - ctx.currentTime) * 10) / 10); },
        };
      }
    }
    (window as unknown as { AudioContext: unknown }).AudioContext = FakeAudioContext;
  });
}

const probe = (page: Page) => page.evaluate(() => (window as unknown as { __probe: Probe }).__probe);

async function setVisibility(page: Page, state: "hidden" | "visible") {
  await page.evaluate((value) => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => value });
    document.dispatchEvent(new Event("visibilitychange"));
  }, state);
}

/** Фон на `seconds` секунд часов браузера: hidden → fastForward → visible. */
async function background(page: Page, seconds: number) {
  await setVisibility(page, "hidden");
  await page.clock.fastForward(seconds * 1000);
  await setVisibility(page, "visible");
}

async function shown(page: Page, index = 0): Promise<number> {
  const text = (await page.locator(".timer-duration-label").nth(index).innerText()).trim();
  const [minutes, seconds] = text.includes(":") ? text.split(":").map(Number) : [0, Number(text)];
  return minutes * 60 + seconds;
}

async function startFromFreePool(page: Page, title: string) {
  await page.getByTestId("my-workout-card").filter({ hasText: title }).click();
  await page.getByRole("button", { name: "Добавить в план" }).click();
  await page.getByRole("button", { name: "Свободный пул" }).click();
  await page.getByRole("button", { name: "Добавить", exact: true }).click();
  const group = page.locator(".plan-week-day-group").filter({ hasText: new RegExp(`^${title}`) });
  await group.getByRole("button", { name: "Начать", exact: true }).click();
  await page.getByRole("button", { name: "Начать", exact: true }).click(); // SessionPreScreen
  await expect(page.getByText("Живая тренировка")).toBeVisible();
}

for (const width of WIDTHS) {
  const theme = THEMES[width as 320 | 390];
  test.describe(`Background timer @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 800 } });

    test("отдых: возврат из фона — остаток по часам, замок взят заново, бип не проигрывается задним числом", async ({
      page,
    }, testInfo) => {
      page.on("dialog", (dialog) => void dialog.accept());
      await installProbes(page);
      await page.clock.install({ time: Date.now() });
      const { consoleErrors, apiFailures } = await openAppAs(
        page, REST_BASE[width as 320 | 390] + testInfo.retry, { theme },
      );
      const writes: string[] = [];
      await startFromFreePool(page, "Тренировка восстановления");

      // Wake lock взят при старте сессии.
      await expect.poll(async () => (await probe(page)).wakeActive).toBe(1);

      // get ready: возврат из фона пересчитывает обратный отсчёт (≤ 5 с, не «заморожен»).
      await background(page, 2);
      expect(await shown(page)).toBeLessThanOrEqual(5);

      await playSets(page, ["8"], false);
      await expect(page.getByRole("heading", { name: "Отдых", exact: true })).toBeVisible();
      page.on("request", (request) => {
        if (request.method() === "POST" && /\/(phase\/next|sets:batch|complete)/.test(request.url())) {
          writes.push(request.url());
        }
      });
      const restBefore = await shown(page);
      expect(restBefore).toBeGreaterThan(50);
      const startsBefore = (await probe(page)).beepStarts.length;
      const requestsBefore = (await probe(page)).wakeRequests;

      // --- фон 20 с, фаза не закончилась: остаток по часам, бип перепланирован на оставшееся ---
      await background(page, 20);
      const afterShort = await shown(page);
      expect(afterShort).toBeLessThanOrEqual(restBefore - 19);
      expect(afterShort).toBeGreaterThan(restBefore - 30);
      const p1 = await probe(page);
      expect(p1.wakeRequests).toBe(requestsBefore + 1); // замок взят заново после возврата
      expect(p1.wakeActive).toBe(1);
      expect(p1.beepStarts.length).toBe(startsBefore + 1);
      expect(p1.beepStarts[p1.beepStarts.length - 1]).toBeGreaterThan(20);
      expect(p1.beepStarts[p1.beepStarts.length - 1]).toBeLessThanOrEqual(afterShort + 1);

      // --- фон 5 мин, фаза закончилась в фоне: 0:00, ни бипа, ни авто-перехода/дубля подхода ---
      await background(page, 300);
      await expect(page.getByRole("heading", { name: "Отдых", exact: true })).toBeVisible();
      expect(await shown(page)).toBe(0);
      const p2 = await probe(page);
      expect(p2.beepStarts.length).toBe(p1.beepStarts.length); // нет «опоздавшего» сигнала
      expect(p2.wakeActive).toBe(1);
      expect(writes).toEqual([]); // возврат ничего не записал и не переключил фазу
      await expectNoHorizontalOverflow(page, "отдых после фона");

      // Фаза переходит ровно один раз — по действию пользователя.
      await clickAndSync(page, "Пропустить отдых", "/phase/next");
      await expect(page.getByText(/Подход 2\/3/)).toBeVisible();
      expect(writes.filter((url) => url.includes("/phase/next"))).toHaveLength(1);

      // Завершение отпускает замок.
      await playSets(page, ["7", "6"]);
      await page.getByRole("button", { name: "Завершить", exact: true }).click();
      await clickAndSync(page, "Сохранить и завершить", "/complete");
      await expect(page.getByText("Тренировка завершена")).toBeVisible();
      await expect.poll(async () => (await probe(page)).wakeActive).toBe(0);

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("interval: возврат из фона — фаза и раунд по серверным часам, один дедлайн-вызов не нужен", async ({
      page,
    }, testInfo) => {
      page.on("dialog", (dialog) => void dialog.accept());
      await installProbes(page);
      await page.clock.install({ time: Date.now() });
      const { consoleErrors, apiFailures } = await openAppAs(
        page, INTERVAL_BASE[width as 320 | 390] + testInfo.retry, { theme },
      );
      const finishes: string[] = [];
      page.on("request", (request) => {
        if (request.url().includes("/blocks/finish")) {
          finishes.push(request.url());
        }
      });
      await startFromFreePool(page, "Интервал фона");

      await expect(page.getByText("Подготовка")).toBeVisible();
      await expect(page.getByText("Работа").first()).toBeVisible({ timeout: 15_000 });
      await expect.poll(async () => (await probe(page)).wakeActive).toBe(1);

      // Раунд 1 работа (0–10 с): фон 14 с → отдых, до конца отдыха ≈ 16 с.
      await background(page, 14);
      await expect(page.getByText("Отдых").first()).toBeVisible();
      const rest = await shown(page);
      expect(rest).toBeGreaterThan(10);
      expect(rest).toBeLessThanOrEqual(18);
      expect((await probe(page)).wakeActive).toBe(1);

      // Ещё 20 с в фоне → раунд 2, работа (позиция ≈ 34 с цикла 30 → 4 с работы), осталось ≈ 2:22.
      await background(page, 20);
      await expect(page.getByText("Работа").first()).toBeVisible();
      const total = await page.getByText(/^Осталось:/).innerText();
      const [m, s] = total.replace("Осталось:", "").trim().split(":").map(Number);
      expect(m * 60 + s).toBeLessThan(180 - 30);
      expect(m * 60 + s).toBeGreaterThan(180 - 50);
      await expectNoHorizontalOverflow(page, "interval после фона");
      expect(finishes).toEqual([]); // дедлайн блока ещё не наступил — завершающего вызова нет

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
