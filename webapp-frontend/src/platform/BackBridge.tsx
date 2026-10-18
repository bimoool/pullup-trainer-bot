// Кнопка «Назад» в странице (браузерный режим). Владелец — WEB-LAYOUT. Логика — backStore.ts.
import { useSyncExternalStore } from "react";

import { isBackVisible, subscribeBackBridge, triggerBack } from "./backStore";

export { browserBackAdapter, handleEscape, adjustOverlayCount, triggerBack } from "./backStore";

/** Кнопка «Назад» в странице; null, если возвращаться некуда. */
export function BackControl() {
  const isVisible = useBackBridgeVisible();
  if (!isVisible) {
    return null;
  }
  return (
    <button type="button" className="web-back" data-testid="web-back" onClick={triggerBack}>
      <span aria-hidden="true">←</span> Назад
    </button>
  );
}

export function useBackBridgeVisible(): boolean {
  return useSyncExternalStore(subscribeBackBridge, isBackVisible, () => false);
}
