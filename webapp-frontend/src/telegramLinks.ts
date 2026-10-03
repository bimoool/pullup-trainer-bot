import { openLink } from "@telegram-apps/sdk";

/** Открывает ссылку вне Mini App (issue #53, волна 2; переиспользуется для
 * оферты — issue #57, п.2) — двойной фолбэк, тот же приём, что уже
 * применён в App.tsx для initData: сначала openLink() из
 * @telegram-apps/sdk (issue #15 — не парсить window.Telegram.WebApp
 * руками), при недоступности/ошибке — window.Telegram.WebApp.openLink
 * (мост telegram-web-app.js, независимый от SDK), финальный фолбэк
 * window.open — для разработки вне Telegram, где оба метода выше не
 * существуют. Mini App не закрывается ни в одном из путей — для оплаты
 * подтверждение приходит отдельным воркером sync_robokassa_payments, для
 * оферты закрывать вовсе не нужно (просто открывает PDF в браузере). */
export function openExternalLink(url: string) {
  try {
    if (openLink.isAvailable()) {
      openLink(url);
      return;
    }
  } catch {
    // падаем в фолбэк ниже
  }
  const telegramWebApp = (window as unknown as { Telegram?: { WebApp?: { openLink?: (u: string) => void } } })
    .Telegram?.WebApp;
  if (telegramWebApp?.openLink) {
    telegramWebApp.openLink(url);
    return;
  }
  window.open(url, "_blank");
}
