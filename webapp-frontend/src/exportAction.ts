import { createExportLink } from "./apiV2";
import { type ExportWebApp, startDownload } from "./exportDownload";

/** Выпускает подписанную ссылку на CSV и запускает скачивание (Analytics и Settings, #267/#268). */
export async function downloadHistoryCsv(initDataRaw: string): Promise<void> {
  const { url } = await createExportLink(initDataRaw);
  const webApp = (window as unknown as { Telegram?: { WebApp?: ExportWebApp } }).Telegram?.WebApp;
  startDownload(url, { webApp, origin: window.location.origin, open: (target) => window.open(target, "_blank") });
}
