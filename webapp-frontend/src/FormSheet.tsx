import type { ReactNode } from "react";

/** Нижний лист-форма (#286 visual-final): «Добавить в план» / «Перенести» открываются листом поверх
 * приглушённого фона (как «⋯» в Планах), а не отдельной страницей. Фон и «Отмена»-тап — `onClose`
 * (тот же обработчик, что у Telegram BackButton экрана). Стили листа — plans.css (`.plans-sheet*`). */
export function FormSheet({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="plans-sheet-backdrop vp-form-sheet-backdrop" data-testid="form-sheet-backdrop" onClick={onClose}>
      <div
        className="plans-sheet vp-form-sheet" role="dialog" aria-modal="true" aria-label={title}
        data-testid="form-sheet" onClick={(event) => event.stopPropagation()}
      >
        <span className="vp-form-sheet-grab" aria-hidden="true" />
        {children}
      </div>
    </div>
  );
}
