import { expect, test } from "@playwright/test";

import { noWakeLock } from "../../fixtures/builderFlow";
import { expectNoHorizontalOverflow, openTab, READY_USER, WIDTHS } from "../../fixtures/parity";
import { openAppAs } from "../../fixtures/setup";

// Crimpd parity — Export (#267): Аналитика → карточка «Экспорт данных — CSV» → «Скачать».
// Только чтение (read-only пользователь READY_USER), поэтому сид не нужен. Скачивание проверяем
// перехватом: в Telegram — window.Telegram.WebApp.downloadFile, иначе — window.open(url).
const THEMES = { 320: "light", 390: "dark" } as const;
const HEADER =
  "source,date,workout,exercise,protocol,set_number,value,unit,effort,note,session_effort,session_comment";

type Captured = { downloads: { url: string; file_name: string }[]; opened: string[] };

for (const width of WIDTHS) {
  const theme = THEMES[width as 320 | 390];
  test.describe(`Export @${width}px ${theme}`, () => {
    test.use({ viewport: { width, height: 800 } });

    test("карточка экспорта; в Telegram — downloadFile с подписанной ссылкой, ответ — CSV с BOM", async ({ page }) => {
      await page.addInitScript(() => {
        const captured: Captured = { downloads: [], opened: [] };
        (window as unknown as { __captured: Captured }).__captured = captured;
        // Мок Telegram ставится позже (openAppAs) — дополняем объект в момент присваивания.
        let telegram: unknown;
        Object.defineProperty(window, "Telegram", {
          configurable: true,
          get: () => telegram,
          set: (value: { WebApp: Record<string, unknown> }) => {
            value.WebApp.downloadFile = (params: { url: string; file_name: string }) => captured.downloads.push(params);
            telegram = value;
          },
        });
        window.open = (url) => {
          captured.opened.push(String(url));
          return null;
        };
      });
      const { consoleErrors, apiFailures } = await openAppAs(page, READY_USER, { theme });
      await openTab(page, "Аналитика");

      const card = page.getByTestId("export-card");
      await expect(card).toContainText("Экспорт данных — CSV");
      await expect(page.getByTestId("export-download")).toHaveText("Скачать");
      await card.scrollIntoViewIfNeeded();
      await expectNoHorizontalOverflow(page, "Аналитика: карточка экспорта");

      const linkResponse = page.waitForResponse((r) => r.url().endsWith("/api/v2/export/link") && r.request().method() === "POST");
      await page.getByTestId("export-download").click();
      expect((await linkResponse).status()).toBe(200);

      await expect.poll(() => page.evaluate(() => (window as unknown as { __captured: Captured }).__captured.downloads.length)).toBe(1);
      const captured = await page.evaluate(() => (window as unknown as { __captured: Captured }).__captured);
      expect(captured.opened).toEqual([]);
      const [download] = captured.downloads;
      expect(download.file_name).toBe("training-history.csv");
      const url = new URL(download.url);
      expect(url.pathname).toBe("/api/v2/export/sessions.csv");
      expect(url.search).toContain("token=");
      expect(download.url).not.toContain("hash=");

      // Ссылка работает без заголовков и отдаёт CSV: BOM + строка заголовка.
      const csv = await page.request.get(download.url);
      expect(csv.status()).toBe(200);
      expect(csv.headers()["content-type"]).toContain("text/csv");
      expect(csv.headers()["content-disposition"]).toContain("attachment");
      const body = await csv.body();
      expect([...body.subarray(0, 3)]).toEqual([0xef, 0xbb, 0xbf]);
      expect(body.toString("utf-8").replace(/^﻿/, "").split("\r\n")[0]).toBe(HEADER);

      // Без токена и без заголовка данных не отдаём.
      expect((await page.request.get("/api/v2/export/sessions.csv")).status()).toBe(401);

      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });

    test("вне Telegram (нет downloadFile) — открывается ссылка", async ({ page }) => {
      await page.addInitScript(() => {
        const opened: string[] = [];
        (window as unknown as { __opened: string[] }).__opened = opened;
        window.open = (url) => {
          opened.push(String(url));
          return null;
        };
      });
      const { consoleErrors, apiFailures } = await openAppAs(page, READY_USER, { theme });
      await openTab(page, "Аналитика");
      await page.getByTestId("export-download").click();
      await expect.poll(() => page.evaluate(() => (window as unknown as { __opened: string[] }).__opened.length)).toBe(1);
      const [opened] = await page.evaluate(() => (window as unknown as { __opened: string[] }).__opened);
      expect(new URL(opened).pathname).toBe("/api/v2/export/sessions.csv");
      expect(opened).toContain("token=");
      expect(noWakeLock(consoleErrors)).toEqual([]);
      expect(apiFailures).toEqual([]);
    });
  });
}
