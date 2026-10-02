import { useEffect, useRef, useState } from "react";

/**
 * M1 (#285): липкий транспорт Live-экрана (live.css `.live-transport`) при экранной клавиатуре
 * остаётся прижатым к низу окна и перекрывает сфокусированное поле. Пока в Live-экране
 * сфокусировано поле ввода, транспорт «отлипает» (`data-field-focus="true"` на `.live-screen`):
 * встаёт обычным блоком в конец потока и прокручивается вместе с контентом.
 */

/** Окно, в течение которого потеря фокуса поля не возвращает транспорт на место: тап по кнопке
 * транспорта («Готово») blur-ит поле на pointerdown — без задержки панель прыгнула бы из-под
 * пальца и клик не дошёл бы до кнопки. */
export const FIELD_BLUR_GRACE_MS = 350;

/** Минимальная форма элемента для проверки (чистая функция — тестируется без DOM). */
export type FocusTargetShape = { tagName?: string; type?: string } | null | undefined;

const NON_TEXT_INPUT_TYPES = new Set([
  "button", "checkbox", "radio", "submit", "reset", "image", "file", "range", "color", "hidden",
]);

/** Поле, при фокусе которого открывается экранная клавиатура. */
export function isTextEntryTarget(target: FocusTargetShape): boolean {
  const tag = target?.tagName?.toUpperCase();
  if (tag === "TEXTAREA") {
    return true;
  }
  if (tag === "INPUT") {
    return !NON_TEXT_INPUT_TYPES.has((target?.type ?? "text").toLowerCase());
  }
  return false;
}

/** true, пока в документе сфокусировано текстовое поле (с задержкой снятия, см. FIELD_BLUR_GRACE_MS). */
export function useLiveFieldFocus(): boolean {
  const [focused, setFocused] = useState(false);
  const holding = useRef(false);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const cancel = () => {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
    };
    const releaseLater = (delay: number) => {
      cancel();
      timer = setTimeout(() => {
        timer = null;
        if (!holding.current) {
          setFocused(false);
        }
      }, delay);
    };
    const onFocusIn = (event: FocusEvent) => {
      if (isTextEntryTarget(event.target as HTMLElement | null)) {
        cancel();
        setFocused(true);
      }
    };
    const onFocusOut = (event: FocusEvent) => {
      if (!isTextEntryTarget(event.target as HTMLElement | null)) {
        return;
      }
      // Фокус ушёл на другой элемент вне транспорта (кнопка «Оценка и заметка», другое поле не в счёт —
      // его focusin отменит таймер) — транспорт возвращается сразу. Если следующего элемента нет
      // (Safari не фокусирует кнопки при тапе) или это кнопка транспорта — ждём окно grace.
      const next = event.relatedTarget as HTMLElement | null;
      const toTransport = next?.closest?.(".live-transport") != null;
      if (next !== null && !toTransport && !isTextEntryTarget(next)) {
        cancel();
        if (!holding.current) {
          setFocused(false);
        }
        return;
      }
      releaseLater(FIELD_BLUR_GRACE_MS);
    };
    // Палец на кнопке транспорта: держим «отлипшее» состояние до конца нажатия.
    const onPointerDown = (event: PointerEvent) => {
      if ((event.target as HTMLElement | null)?.closest?.(".live-transport")) {
        holding.current = true;
        cancel();
      }
    };
    const onPointerEnd = () => {
      if (holding.current) {
        holding.current = false;
        releaseLater(FIELD_BLUR_GRACE_MS);
      }
    };
    document.addEventListener("focusin", onFocusIn);
    document.addEventListener("focusout", onFocusOut);
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("pointerup", onPointerEnd, true);
    document.addEventListener("pointercancel", onPointerEnd, true);
    return () => {
      cancel();
      document.removeEventListener("focusin", onFocusIn);
      document.removeEventListener("focusout", onFocusOut);
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("pointerup", onPointerEnd, true);
      document.removeEventListener("pointercancel", onPointerEnd, true);
    };
  }, []);
  // Поле могли убрать из DOM (смена фазы: Chrome при удалении сфокусированного элемента
  // focusout не шлёт) — пока «отлипшее» состояние включено, сверяем его с реальным фокусом.
  useEffect(() => {
    if (!focused) {
      return;
    }
    const poll = setInterval(() => {
      if (!holding.current && !isTextEntryTarget(document.activeElement as HTMLElement | null)) {
        setFocused(false);
      }
    }, FIELD_BLUR_GRACE_MS);
    return () => clearInterval(poll);
  }, [focused]);
  return focused;
}
