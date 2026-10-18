// Хранилище моста «Назад» (без React/JSX — юнит-тесты). Мост «Назад» для браузера. В Mini App «Назад» ведёт Telegram BackButton (useBackButton → backButtonStack);
// в браузере тот же стек обработчиков показывается кнопкой в странице. Владелец — WEB-LAYOUT.
type Listener = () => void;

const subscribers = new Set<Listener>();
let visible = false;
let clickListener: Listener | null = null;
let overlayCount = 0;

function emit() {
  subscribers.forEach((listener) => listener());
}

/** Адаптер для createBackButtonStack в браузерном режиме. */
export const browserBackAdapter = {
  setVisible(next: boolean) {
    if (visible !== next) {
      visible = next;
      emit();
    }
  },
  subscribe(listener: Listener) {
    clickListener = listener;
    return () => {
      if (clickListener === listener) {
        clickListener = null;
      }
    };
  },
};

/** Нажатие in-page «Назад»: верхний обработчик стека. */
export function triggerBack(): void {
  clickListener?.();
}

/** Escape закрывает шторку только пока открыта шторка (экран-оверлей useBackButton(hideNav=false)). */
export function adjustOverlayCount(delta: number): void {
  overlayCount = Math.max(0, overlayCount + delta);
}

/** Обработчик Escape (вешает AppShell): true — событие поглощено. */
export function handleEscape(event: Pick<KeyboardEvent, "key" | "defaultPrevented" | "isComposing">): boolean {
  if (event.key !== "Escape" || event.defaultPrevented || event.isComposing || overlayCount === 0 || clickListener === null) {
    return false;
  }
  triggerBack();
  return true;
}

export function subscribeBackBridge(listener: Listener) {
  subscribers.add(listener);
  return () => void subscribers.delete(listener);
}

export function isBackVisible(): boolean {
  return visible;
}

export function resetBackBridgeForTests(): void {
  visible = false;
  clickListener = null;
  overlayCount = 0;
  subscribers.clear();
}
