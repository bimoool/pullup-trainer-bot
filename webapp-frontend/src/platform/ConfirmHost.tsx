// Шторка подтверждения вместо window.confirm в браузерном режиме. Владелец — WEB-LAYOUT.
import { useEffect, useRef, useSyncExternalStore } from "react";

import { answerConfirm, currentConfirm, subscribeConfirm } from "./confirmStore";

export function ConfirmHost() {
  const pending = useSyncExternalStore(subscribeConfirm, currentConfirm, () => null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!pending) {
      return;
    }
    const previous = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        answerConfirm(false);
      } else if (event.key === "Tab") {
        const nodes = [cancelRef.current, confirmRef.current].filter(Boolean) as HTMLElement[];
        const index = nodes.indexOf(document.activeElement as HTMLElement);
        event.preventDefault();
        nodes[(index + (event.shiftKey ? nodes.length - 1 : 1)) % nodes.length]?.focus();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      previous?.focus?.();
    };
  }, [pending]);
  if (!pending) {
    return null;
  }
  return (
    <div className="web-confirm-layer" data-testid="web-confirm">
      <div className="web-confirm-backdrop" onClick={() => answerConfirm(false)} />
      <div className="web-confirm-sheet" role="alertdialog" aria-modal="true" aria-label="Подтверждение" aria-describedby="web-confirm-text">
        <p id="web-confirm-text" className="web-confirm-text">{pending.message}</p>
        <div className="web-confirm-actions">
          <button ref={cancelRef} type="button" className="web-confirm-btn" data-testid="web-confirm-cancel" onClick={() => answerConfirm(false)}>Отмена</button>
          <button ref={confirmRef} type="button" className="web-confirm-btn web-confirm-btn-primary" data-testid="web-confirm-ok" onClick={() => answerConfirm(true)}>Да</button>
        </div>
      </div>
    </div>
  );
}
