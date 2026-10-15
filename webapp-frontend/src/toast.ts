// Короткие сообщения об успехе («Удалено», «Тренировка отменена») — аудит staging 6475bc0, п. 4: после
// подтверждения через WebApp.showConfirm пользователь должен видеть, что действие выполнено. Хранилище без React
// (юнит-тест tests/toast.test.ts); показывает ToastHost.tsx, смонтированный один раз в App.

export type Toast = { id: number; text: string };
type Listener = (toast: Toast | null) => void;

export const TOAST_DURATION_MS = 2500;

export function createToastStore(schedule: (fn: () => void, ms: number) => unknown = setTimeout,
  cancel: (handle: unknown) => void = (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>)) {
  let current: Toast | null = null;
  let nextId = 1;
  let timer: unknown = null;
  const listeners = new Set<Listener>();
  const emit = () => listeners.forEach((listener) => listener(current));
  return {
    /** Новое сообщение заменяет предыдущее и живёт TOAST_DURATION_MS. */
    show(text: string): void {
      if (timer !== null) {
        cancel(timer);
      }
      const toast = { id: nextId++, text };
      current = toast;
      emit();
      timer = schedule(() => {
        timer = null;
        if (current?.id === toast.id) {
          current = null;
          emit();
        }
      }, TOAST_DURATION_MS);
    },
    current: () => current,
    subscribe(listener: Listener): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

const store = createToastStore();

export const showToast = (text: string): void => store.show(text);
export const currentToast = (): Toast | null => store.current();
export const subscribeToast = (listener: Listener): (() => void) => store.subscribe(listener);
