/** N2 (#293): что показать, когда сервер знает активную сессию, мешающую старту. */
export type ActiveConflictKind = "finish_pending" | "continue";

/** Минимум, нужный решению: id активной сессии с сервера и черновик из IndexedDB (если есть). */
export function classifyActiveConflict(
  activeSessionId: number,
  queued: { serverSessionId: number; completeRequested: unknown } | null,
): ActiveConflictKind {
  // Завершение этой самой сессии уже поставлено в очередь/летит: «Продолжить» вело бы в
  // уже законченную тренировку — вместо этого «Завершение отправляется…» с повтором.
  if (queued !== null && queued.completeRequested !== null && queued.serverSessionId === activeSessionId) {
    return "finish_pending";
  }
  return "continue";
}
