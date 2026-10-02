// Просроченный/невалидный initData (#224, п.9): бэкенд отвечает 401 (app/web/auth.py — initData
// живёт 12 ч, внутри Telegram его не обновить без повторного открытия Mini App). Вместо «голого»
// «Invalid Telegram initData» говорим, что делать. Общий для api.ts и apiV2.ts.

export const SESSION_EXPIRED_MESSAGE = "Сессия Telegram устарела. Закрой приложение и открой его заново из бота.";

export function isSessionExpiredMessage(message: string): boolean {
  return message === SESSION_EXPIRED_MESSAGE;
}
