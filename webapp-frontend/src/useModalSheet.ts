import { useEffect, useRef, type RefObject } from "react";

import { useBackButton } from "./useBackButton";

const FOCUSABLE = "button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex='-1'])";

/**
 * Контракт модальной шторки (#290): фокус уходит в диалог при открытии, Tab не выходит за его
 * пределы, Escape и Telegram BackButton закрывают, фокус возвращается на открывавший элемент.
 * Шторка смонтирована = открыта; ref вешается на role=dialog (tabIndex=-1, aria-modal=true).
 */
export function useModalSheet(onClose: () => void, returnFocusTo?: HTMLElement | null): RefObject<HTMLDivElement> {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useBackButton(onClose, [], true, false);

  useEffect(() => {
    const dialog = dialogRef.current;
    const opener = returnFocusTo ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    dialog?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab" || dialog === null) {
        return;
      }
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (!dialog.contains(active) || (event.shiftKey && (active === first || active === dialog))) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (opener !== null && opener.isConnected) {
        opener.focus();
      }
    };
  }, [returnFocusTo]);

  return dialogRef;
}
