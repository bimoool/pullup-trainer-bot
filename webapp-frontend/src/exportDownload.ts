// Экспорт истории в CSV (#267): как отдать скачивание. Внутри Telegram —
// Telegram.WebApp.downloadFile (Bot API 8.0+), иначе открываем ссылку. Ссылка
// подписанная и короткоживущая (createExportLink в apiV2.ts): initData в query-строку не кладём.

export type DownloadFileParams = { url: string; file_name: string };

export type ExportWebApp = {
  downloadFile?: (params: DownloadFileParams, callback?: (accepted: boolean) => void) => void;
};

export type ExportDeps = {
  webApp: ExportWebApp | undefined;
  origin: string;
  open: (url: string) => void;
};

export const EXPORT_FILE_NAME = "training-history.csv";

export function absoluteUrl(origin: string, path: string): string {
  return /^https?:\/\//.test(path) ? path : `${origin.replace(/\/$/, "")}${path.startsWith("/") ? "" : "/"}${path}`;
}

/** Возвращает способ, которым запущено скачивание. */
export function startDownload(path: string, deps: ExportDeps): "telegram" | "open" {
  const url = absoluteUrl(deps.origin, path);
  if (typeof deps.webApp?.downloadFile === "function") {
    // telegram-web-app.js определяет downloadFile всегда, но на клиентах < Bot API 8.0 (и вне
    // Telegram) метод бросает WebAppMethodUnsupported — тогда открываем ссылку (#224 review).
    try {
      deps.webApp.downloadFile({ url, file_name: EXPORT_FILE_NAME });
      return "telegram";
    } catch {
      // падаем в обычное открытие ссылки ниже
    }
  }
  deps.open(url);
  return "open";
}
