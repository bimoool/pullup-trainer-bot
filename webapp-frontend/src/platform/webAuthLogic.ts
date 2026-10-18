// Чистая логика экрана входа в браузере (без React/DOM — тестируется через node --test). Владелец — WEB-AUTH.

export type PollStatus = "pending" | "signed_in" | "denied" | "expired" | "not_found" | "too_many";

export type LoginPhase =
  | { kind: "idle" }
  | { kind: "requesting" }
  | { kind: "waiting"; requestId: string; code: string; botLink: string | null; expiresAtMs: number }
  | { kind: "signed_in" }
  | { kind: "denied" }
  | { kind: "expired" }
  | { kind: "rate_limited" }
  | { kind: "error"; message: string };

/** Пауза до следующего опроса: базовый интервал сервера, мягко растёт при долгом ожидании, потолок 6 с; при 429 — x3. */
export function nextPollDelayMs(attempt: number, baseSeconds: number, rateLimited = false): number {
  const base = Math.max(1, baseSeconds) * 1000;
  const grown = base * (1 + Math.floor(Math.max(0, attempt) / 20) * 0.5);
  return Math.min(rateLimited ? grown * 3 : grown, rateLimited ? 15000 : 6000);
}

export function secondsLeft(expiresAtMs: number, nowMs: number): number {
  return Math.max(0, Math.ceil((expiresAtMs - nowMs) / 1000));
}

export function formatCountdown(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** Для скринридера: «4 8 2 1», чтобы код не читался как «четыре тысячи восемьсот двадцать один». */
export function spokenCode(code: string): string {
  return code.split("").join(" ");
}

/** Результат одного опроса -> следующая фаза экрана (null — продолжать ждать в текущей). */
export function phaseAfterPoll(status: PollStatus): LoginPhase | null {
  switch (status) {
    case "signed_in":
      return { kind: "signed_in" };
    case "denied":
      return { kind: "denied" };
    case "expired":
    case "not_found":
      return { kind: "expired" };
    default:
      return null;
  }
}

export const LOGIN_COPY = {
  title: "Вход через Telegram",
  lead: "Войдите тем же аккаунтом, что и в Telegram: тренировки и история будут общими.",
  start: "Войти через Telegram",
  requesting: "Готовим вход…",
  waitingHeading: "Код для подтверждения",
  waitingHint: "Откройте бота и нажмите «Подтвердить», только если код в сообщении совпадает с этим.",
  openBot: "Открыть бота в Telegram",
  noLinkHint: "Откройте бота в Telegram и отправьте ему это сообщение:",
  cancel: "Отменить",
  signedIn: "Готово, входим…",
  denied: "Вход отменён в Telegram.",
  expired: "Время на подтверждение вышло или код уже использован.",
  rateLimited: "Слишком много попыток. Подождите минуту и попробуйте снова.",
  retry: "Запросить новый код",
  networkError: "Не удалось связаться с сервером. Проверьте интернет и попробуйте снова.",
  safety: "Не подтверждайте вход, если вас об этом просит кто-то другой.",
} as const;
