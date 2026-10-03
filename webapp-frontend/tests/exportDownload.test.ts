import assert from "node:assert/strict";
import { test } from "node:test";

import { absoluteUrl, EXPORT_FILE_NAME, startDownload } from "../src/exportDownload.ts";

test("absoluteUrl: относительный путь получает origin, абсолютный не трогаем", () => {
  assert.equal(absoluteUrl("https://app.example/", "/api/v2/export/sessions.csv?token=a"), "https://app.example/api/v2/export/sessions.csv?token=a");
  assert.equal(absoluteUrl("https://app.example", "https://x.y/f.csv"), "https://x.y/f.csv");
});

test("startDownload: в Telegram — downloadFile с именем файла, без open", () => {
  const calls: unknown[] = [];
  const opened: string[] = [];
  const how = startDownload("/api/v2/export/sessions.csv?token=t", {
    webApp: { downloadFile: (params) => calls.push(params) },
    origin: "https://app.example",
    open: (url) => opened.push(url),
  });
  assert.equal(how, "telegram");
  assert.deepEqual(calls, [{ url: "https://app.example/api/v2/export/sessions.csv?token=t", file_name: EXPORT_FILE_NAME }]);
  assert.deepEqual(opened, []);
});

test("startDownload: без downloadFile — открывает ссылку", () => {
  const opened: string[] = [];
  const how = startDownload("/api/v2/export/sessions.csv?token=t", {
    webApp: {}, origin: "https://app.example", open: (url) => opened.push(url),
  });
  assert.equal(how, "open");
  assert.deepEqual(opened, ["https://app.example/api/v2/export/sessions.csv?token=t"]);
});

test("downloadFile бросает (клиент < Bot API 8.0 / вне Telegram) → открываем ссылку", () => {
  const opened: string[] = [];
  const how = startDownload("/api/v2/export/x.csv", {
    webApp: { downloadFile: () => { throw new Error("WebAppMethodUnsupported"); } },
    origin: "https://app.example",
    open: (url) => opened.push(url),
  });
  assert.equal(how, "open");
  assert.deepEqual(opened, ["https://app.example/api/v2/export/x.csv"]);
});
