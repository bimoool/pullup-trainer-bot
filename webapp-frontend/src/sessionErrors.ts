// Просроченный/невалидный initData (#224, п.9): бэкенд отвечает 401 (app/web/auth.py — initData
// живёт 12 ч, внутри Telegram его не обновить без повторного открытия Mini App). Вместо «голого»
// «Invalid Telegram initData» говорим, что делать. Общий для api.ts и apiV2.ts.

export const SESSION_EXPIRED_MESSAGE = "Сессия Telegram устарела. Закрой приложение и открой его заново из бота.";

export function isSessionExpiredMessage(message: string): boolean {
  return message === SESSION_EXPIRED_MESSAGE;
}

/**
 * Запасной текст ошибки запроса, когда у ответа нет строкового `detail` / `detail.message` (422 Pydantic — массив,
 * 409 `course_setup_required` — только код). Раньше на экран попадало «PUT /api/v2/… failed: 422» (первый обычный
 * пользователь на staging). Код ответа остаётся в тексте и в полях ошибки (`status`/`code`) — классификация по ним
 * не меняется; адрес запроса пользователю не показывается.
 */
export function httpFailureMessage(status: number): string {
  if (status === 400 || status === 422) {
    return `Сервер не принял введённые данные — проверьте числа (только цифры, дробная часть через запятую) и попробуйте ещё раз. Код ${status}.`;
  }
  if (status === 404) {
    return "Не нашлось на сервере — обновите экран. Код 404.";
  }
  if (status === 409) {
    return "Сейчас это действие недоступно — обновите экран и попробуйте ещё раз. Код 409.";
  }
  if (status >= 500) {
    return `Сервер временно не отвечает — попробуйте ещё раз чуть позже. Код ${status}.`;
  }
  return `Запрос не выполнен — попробуйте ещё раз. Код ${status}.`;
}
