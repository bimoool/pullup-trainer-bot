/**
 * Чистые помощники Live-экрана для review-шторки (#285 M3/M2): что делает Telegram BackButton и
 * как циклично ходит Tab внутри модального диалога.
 */

export type BackAction = "close-review" | "ignore" | "confirm-finish" | "leave";

/**
 * BackButton на живой тренировке (docs/PROJECT_SPEC.md §2 п.12): при открытой review-шторке он только
 * закрывает её — введённые оценка и заметка остаются, завершения без review нет. Когда завершение
 * уже поставлено в очередь (ждёт сети/ответа сервера), Back уводит с экрана (#287): результат лежит
 * в IndexedDB и досылается позже; если уйти нельзя (canLeave=false: лаба без выхода или запрос
 * завершения прямо сейчас в полёте — Summary вот-вот откроется) — нажатие игнорируется. Иначе прежнее поведение: confirm «Закончить сессию?» и завершение без review.
 */
export function backButtonAction(state: { reviewOpen: boolean; finishing: boolean; canLeave?: boolean }): BackAction {
  if (state.reviewOpen) {
    return "close-review";
  }
  if (state.finishing) {
    return state.canLeave ? "leave" : "ignore";
  }
  return "confirm-finish";
}

/** Следующий индекс фокуса при Tab (backwards = Shift+Tab) среди `count` фокусируемых в диалоге.
 * current = -1 — фокус на самом диалоге (или вне списка). null — фокусировать нечего (Tab гасим). */
export function nextTrapIndex(count: number, current: number, backwards: boolean): number | null {
  if (count <= 0) {
    return null;
  }
  if (current < 0 || current >= count) {
    return backwards ? count - 1 : 0;
  }
  if (backwards) {
    return current === 0 ? count - 1 : current - 1;
  }
  return current === count - 1 ? 0 : current + 1;
}

export const FOCUSABLE_SELECTOR =
  'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';
