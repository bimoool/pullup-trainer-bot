import { useEffect, useRef } from "react";

import { useBackButton } from "./useBackButton";

export type SheetAction = {
  key: string;
  label: string;
  onSelect: () => void;
  /** Деструктивное действие — красным. */
  danger?: boolean;
  disabled?: boolean;
  testId?: string;
};

type Props = {
  title: string;
  actions: SheetAction[];
  onClose: () => void;
  testId?: string;
  /** «⋯», с которой открыли лист (#288): туда возвращается фокус. На iOS тап не фокусирует кнопку,
   * поэтому document.activeElement при открытии ненадёжен — opener передаёт родитель. */
  returnFocusTo?: HTMLElement | null;
};

const FOCUSABLE = "button:not(:disabled)";

/**
 * Нижний лист действий (#286 B): «⋯» строки дня и плана в «Планах». Закрывается тапом по фону,
 * Escape (document-слушатель, пока лист открыт — не зависит от того, где фокус, #288), «Отмена»
 * и Telegram BackButton (стек: пока лист смонтирован, «назад» получает он); фокус уходит в лист
 * при открытии и возвращается на «⋯» при закрытии (если она ещё в DOM; иначе фокус ставит родитель —
 * например, на кнопку подтверждения). Листом управляет родитель (смонтирован = открыт), поэтому
 * BackButton занимает стек ровно на время показа.
 */
export function ActionSheet({ title, actions, onClose, testId = "plans-sheet", returnFocusTo = null }: Props) {
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
      // фокус не уходит за пределы листа (aria-modal)
      const focusable = Array.from(dialog.querySelectorAll<HTMLButtonElement>(FOCUSABLE));
      if (focusable.length === 0) {
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

  return (
    <div className="plans-sheet-backdrop" data-testid={`${testId}-backdrop`} onClick={onClose}>
      <div
        ref={dialogRef} className="plans-sheet" role="dialog" aria-modal="true" aria-label={title}
        tabIndex={-1} data-testid={testId} onClick={(event) => event.stopPropagation()}
      >
        <p className="plans-sheet-title">{title}</p>
        {actions.map((action) => (
          <button
            key={action.key} type="button" disabled={action.disabled} data-testid={action.testId}
            className={action.danger ? "plans-sheet-action plans-sheet-danger" : "plans-sheet-action"}
            onClick={() => {
              onClose();
              action.onSelect();
            }}
          >
            {action.label}
          </button>
        ))}
        <button type="button" className="plans-sheet-action plans-sheet-cancel" onClick={onClose}>
          Отмена
        </button>
      </div>
    </div>
  );
}

/** Кнопка «⋯» (иконка, не текст) — открывает лист; имя для скринридеров и тестов — в aria-label. */
export function MoreButton({ label, onClick, testId, focusKey }: {
  label: string; onClick: (opener: HTMLButtonElement) => void; testId?: string;
  /** Ключ для возврата фокуса после подтверждения/«Отмены», когда «⋯» была скрыта (data-focus-key). */
  focusKey?: string;
}) {
  return (
    <button
      type="button" className="plans-more" aria-label={label} aria-haspopup="dialog" data-testid={testId}
      data-focus-key={focusKey} onClick={(event) => onClick(event.currentTarget)}
    >
      <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false">
        <circle cx="5" cy="12" r="2" />
        <circle cx="12" cy="12" r="2" />
        <circle cx="19" cy="12" r="2" />
      </svg>
    </button>
  );
}

/** Полоса прогресса «сделано из плана» (role=progressbar). aria — в процентах 0..100 (при пустом плане
 * valuemax=0 некорректен, #288), понятная скринридеру фраза «x из y» — в aria-valuetext. */
export function PlanProgressBar({ done, total, percent, label, testId }: {
  done: number; total: number; percent: number; label: string; testId?: string;
}) {
  return (
    <div
      className="plans-progress" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100}
      aria-valuenow={percent} aria-valuetext={total > 0 ? `${done} из ${total}` : "Ничего не запланировано"}
      data-testid={testId} data-percent={percent} data-done={done} data-total={total}
    >
      <div className="plans-progress-fill" style={{ width: `${percent}%` }} />
    </div>
  );
}
