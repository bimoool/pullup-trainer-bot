import { createExportLink } from "./apiV2";
import { type ExportWebApp, startDownload } from "./exportDownload";
import { openExternalLink } from "./telegramLinks";

/** Выпускает подписанную ссылку на CSV и запускает скачивание (Analytics и Settings, #267/#268). */
export async function downloadHistoryCsv(initDataRaw: string): Promise<void> {
  const { url } = await createExportLink(initDataRaw);
  const webApp = (window as unknown as { Telegram?: { WebApp?: ExportWebApp } }).Telegram?.WebApp;
  // Клиенты до Bot API 8.0 (нет downloadFile): window.open после await блокируется WKWebView как
  // «всплывающее окно» — открываем через Telegram.WebApp.openLink (#224).
  startDownload(url, { webApp, origin: window.location.origin, open: openExternalLink });
}
