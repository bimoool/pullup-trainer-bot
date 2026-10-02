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
};

/**
 * Нижний лист действий (#286 B): «⋯» строки дня и плана в «Планах». Закрывается тапом по фону,
 * Escape, «Отмена» и Telegram BackButton (стек: пока лист смонтирован, «назад» получает он);
 * фокус уходит в лист при открытии и возвращается на «⋯» при закрытии. Листом управляет родитель
 * (смонтирован = открыт), поэтому BackButton занимает стек ровно на время показа.
 */
export function ActionSheet({ title, actions, onClose, testId = "plans-sheet" }: Props) {
  const dialogRef = useRef<HTMLDivElement>(null);
  useBackButton(onClose);

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialogRef.current?.focus();
    return () => {
      if (opener !== null && opener.isConnected) {
        opener.focus();
      }
    };
  }, []);

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab") {
      return;
    }
    // фокус не уходит за пределы листа
    const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []);
    if (focusable.length === 0) {
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === dialogRef.current)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div className="plans-sheet-backdrop" data-testid={`${testId}-backdrop`} onClick={onClose}>
      <div
        ref={dialogRef} className="plans-sheet" role="dialog" aria-modal="true" aria-label={title}
        tabIndex={-1} data-testid={testId} onClick={(event) => event.stopPropagation()} onKeyDown={handleKeyDown}
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
export function MoreButton({ label, onClick, testId }: { label: string; onClick: () => void; testId?: string }) {
  return (
    <button type="button" className="plans-more" aria-label={label} aria-haspopup="dialog" data-testid={testId} onClick={onClick}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false">
        <circle cx="5" cy="12" r="2" />
        <circle cx="12" cy="12" r="2" />
        <circle cx="19" cy="12" r="2" />
      </svg>
    </button>
  );
}

/** Полоса прогресса «сделано из плана» (role=progressbar; значения читаются и тестами, и скринридерами). */
export function PlanProgressBar({ done, total, percent, label, testId }: {
  done: number; total: number; percent: number; label: string; testId?: string;
}) {
  return (
    <div
      className="plans-progress" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={total}
      aria-valuenow={done} data-testid={testId} data-percent={percent}
    >
      <div className="plans-progress-fill" style={{ width: `${percent}%` }} />
    </div>
  );
}
