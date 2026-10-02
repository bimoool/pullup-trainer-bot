import { useEffect, useRef, useState } from "react";

import { deleteSession, type SessionResponseV2 } from "./apiV2";
import { journalEntryTitle } from "./journalFormat";
import { formatSessionTime } from "./journalTime";
import {
  JOURNAL_DELETE_CONFIRM, JOURNAL_SHEET_LABELS, journalSheetActions, type JournalSheetAction,
} from "./journalSheet";
import { useBackButton } from "./useBackButton";

const FOCUSABLE = "button:not([disabled])";

/**
 * Шторка записи Журнала v2 (#280, как в Crimpd): тап по карточке → «Открыть / Изменить / Повторить /
 * Открыть тренировку / Удалить / Отмена». Действия переиспользуют существующие экраны и удаление;
 * доступность — по тем же флагам записи, что и на экране деталей (journalSheetActions).
 * Закрывается фоном, Escape, «Отмена» и Telegram BackButton; фокус уходит в шторку и возвращается
 * на карточку; ошибка удаления остаётся в шторке (тупика нет).
 */
export function JournalEntrySheet({
  initDataRaw, session, timeZone, canOpenWorkout, returnFocusTo, onClose, onOpen, onEdit, onClone, onOpenWorkout, onDeleted,
}: {
  initDataRaw: string;
  session: SessionResponseV2;
  timeZone: string;
  canOpenWorkout: boolean;
  /** Карточка, с которой открыли шторку — туда возвращается фокус. */
  returnFocusTo: HTMLElement | null;
  onClose: () => void;
  onOpen: () => void;
  onEdit: () => void;
  onClone: () => void;
  onOpenWorkout: () => void;
  onDeleted: (sessionId: number) => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const deleteInFlight = useRef(false);
  const closeRef = useRef(() => {});
  // Пока удаление идёт, шторка не закрывается (иначе ответ придёт уже «в никуда»).
  closeRef.current = () => {
    if (!deleteInFlight.current) {
      onClose();
    }
  };
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useBackButton(() => closeRef.current(), [], true, false);

  // Во время удаления кнопки disabled → браузер роняет фокус на body; возвращаем его на шторку.
  useEffect(() => {
    if (deleting && !dialogRef.current?.contains(document.activeElement)) {
      dialogRef.current?.focus();
    }
  }, [deleting]);

  useEffect(() => {
    const dialog = dialogRef.current;
    // Сначала сама шторка, а не первое действие: зажатый Enter/Space (открыл карточку) не нажмёт «Открыть» сразу.
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
      // Фокус не выходит за шторку (aria-modal).
      const items = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) {
        // Все кнопки заблокированы (идёт удаление): фокус остаётся на шторке, а не уходит на страницу под ней.
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (document.activeElement === dialog) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (!dialog.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (returnFocusTo?.isConnected) {
        returnFocusTo.focus();
      }
    };
  }, [returnFocusTo]);

  async function handleDelete() {
    if (deleteInFlight.current) {
      return;
    }
    if (!window.confirm(JOURNAL_DELETE_CONFIRM)) {
      return;
    }
    deleteInFlight.current = true;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteSession(initDataRaw, session.id);
      onDeleted(session.id);
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : String(error));
      deleteInFlight.current = false;
      setDeleting(false);
    }
  }

  const handlers: Record<JournalSheetAction, () => void> = {
    open: onOpen, edit: onEdit, clone: onClone, workout: onOpenWorkout, delete: () => void handleDelete(),
  };
  const actions = journalSheetActions(session, { canOpenWorkout });
  const title = journalEntryTitle(session);

  return (
    <div className="home-sheet-backdrop" data-testid="journal-entry-sheet-backdrop" onClick={() => closeRef.current()}>
      <div
        ref={dialogRef} className="home-sheet journal-sheet" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}
        data-testid="journal-entry-sheet" onClick={(event) => event.stopPropagation()}
      >
        <p className="journal-sheet-title">
          <span className="journal-sheet-name">{title}</span>
          <span className="journal-sheet-time">{formatSessionTime(session.performed_at, timeZone)}</span>
        </p>
        {deleteError !== null && <p className="gap-banner" data-testid="journal-sheet-error">{deleteError}</p>}
        {actions.map((action) => (
          <button
            key={action} type="button" disabled={deleting}
            className={action === "delete" ? "home-sheet-action journal-sheet-danger" : "home-sheet-action"}
            data-testid={`journal-sheet-${action}`} onClick={handlers[action]}
          >
            {action === "delete" && deleting ? "Удаляю…" : JOURNAL_SHEET_LABELS[action]}
          </button>
        ))}
        <button
          type="button" className="home-sheet-action home-sheet-cancel" disabled={deleting}
          data-testid="journal-sheet-cancel" onClick={() => closeRef.current()}
        >
          Отмена
        </button>
      </div>
    </div>
  );
}
