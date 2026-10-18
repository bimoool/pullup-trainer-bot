// Браузерная сессия (WEB-AUTH): выход. Токен — HttpOnly cookie, сервер отзывает его и стирает cookie.
import { logoutRequest } from "./webAuthApi.ts";

/** Ключ persister'а react-query (OfflineQueryProvider): данные прошлого пользователя не должны остаться на общем браузере. */
const QUERY_CACHE_KEY = "pullup-v2-query-cache";

export function clearLocalUserData(storage: Pick<Storage, "removeItem"> | undefined = safeLocalStorage()): void {
  try {
    storage?.removeItem(QUERY_CACHE_KEY);
  } catch {
    // хранилище недоступно (приватное окно) — нечего чистить
  }
}

function safeLocalStorage(): Storage | undefined {
  try {
    return typeof window === "undefined" ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}

export function signOutBrowser(): void {
  void logoutRequest()
    .catch(() => undefined)
    .finally(() => {
      clearLocalUserData();
      window.location.reload();
    });
}
