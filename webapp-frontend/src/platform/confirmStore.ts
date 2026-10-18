// Подтверждение действия в странице (браузерный режим): confirmAction() кладёт запрос сюда, ConfirmHost
// (AppShell) показывает шторку и резолвит промис. Без React — чистая логика, проверяется юнит-тестом.
export type PendingConfirm = { message: string; resolve: (confirmed: boolean) => void };

type Listener = () => void;
const listeners = new Set<Listener>();
let queue: PendingConfirm[] = [];

function emit() {
  listeners.forEach((listener) => listener());
}

export function requestConfirm(message: string): Promise<boolean> {
  return new Promise((resolve) => {
    queue = [...queue, { message, resolve }];
    emit();
  });
}

export function currentConfirm(): PendingConfirm | null {
  return queue[0] ?? null;
}

export function answerConfirm(confirmed: boolean): void {
  const [head, ...rest] = queue;
  if (!head) {
    return;
  }
  queue = rest;
  head.resolve(confirmed);
  emit();
}

export function subscribeConfirm(listener: Listener): () => void {
  listeners.add(listener);
  return () => void listeners.delete(listener);
}
