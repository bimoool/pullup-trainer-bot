import { Button, Section } from "@telegram-apps/telegram-ui";
import { useRef, useState } from "react";

import { deleteSession, type SessionResponseV2 } from "./apiV2";
import { effortWithWord } from "./effortScale";
import { describeJournalBlock } from "./journalFormat";
import { formatSessionDateTime, formatSessionTime } from "./journalTime";
import { JOURNAL_KIND_LABELS, journalKind } from "./journalKind";
import { formatDurationHm } from "./journalLog";
import { JOURNAL_DELETE_CONFIRM } from "./journalSheet";
import { JournalV2CloneForm, JournalV2EditForm } from "./JournalV2Edit";
import { useBackButton } from "./useBackButton";

/** Карточка завершённой TrainingSession (Журнал v2). Каждый блок сессии
 * рендерится независимо — ни один блок не определяет вид всей карточки. */
export function JournalSessionCard({
  session, timeZone, onOpen,
}: {
  session: SessionResponseV2;
  /** Часовой пояс журнала (профиль) — тот же, что у заголовков дней. */
  timeZone: string;
  /** Тап/Enter по карточке (#280: открывает шторку действий; element — куда вернуть фокус). */
  onOpen: (sessionId: number, element: HTMLElement) => void;
}) {
  const kind = journalKind(session);
  return (
    <div
      className="history-card history-card-clickable journal-card"
      data-kind={kind}
      role="button"
      tabIndex={0}
      data-testid="journal-card"
      aria-haspopup="dialog"
      onClick={(event) => onOpen(session.id, event.currentTarget)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen(session.id, event.currentTarget);
        }
      }}
    >
      <span className="journal-card-marker" aria-hidden="true" data-testid="journal-kind-marker" />
      <div className="journal-card-body">
        {/* Компактная карточка: строка 1 — название + время, строка 2 — тип/длительность/блоки. */}
        <p className="journal-card-title">
          <span className="journal-card-name">{session.title ?? "Тренировка"}</span>
          <span className="journal-card-time">{formatSessionTime(session.performed_at, timeZone)}</span>
        </p>
        <p className="journal-card-meta">
          {kind !== "plan" && <span className="journal-kind-label">{JOURNAL_KIND_LABELS[kind]}</span>}
          {session.duration_seconds != null && (
            <span data-testid="journal-activity-duration">Длительность: {formatDurationHm(session.duration_seconds)}</span>
          )}
          {session.effort !== null && (
            <span className="journal-effort" data-effort={String(Number(session.effort))} data-testid="journal-card-effort">
              Усилие {Number(session.effort)}
            </span>
          )}
          {session.blocks.map((block) => {
            const view = describeJournalBlock(block);
            return (
              <span key={block.order_index} className="journal-block">
                {view.header !== null && <span className="journal-block-header">{view.header}</span>}
                <span className="journal-block-fact">{view.fact}</span>
              </span>
            );
          })}
        </p>
      </div>
    </div>
  );
}

/** Ошибка догрузки + «Показать ещё» под списком сессий. */
export function JournalV2Footer({
  hasMore, loadingMore, moreError, onLoadMore,
}: {
  hasMore: boolean;
  loadingMore: boolean;
  moreError: string | null;
  onLoadMore: () => void;
}) {
  return (
    <div>
      {moreError !== null &&(
        <p className="gap-banner">Не удалось загрузить ещё: {moreError}. Загруженные тренировки сохранены.</p>
      )}
      {hasMore && (
        <Button mode="outline" size="m" stretched loading={loadingMore} onClick={onLoadMore}>
          Показать ещё
        </Button>
      )}
    </div>
  );
}

/** Детали сессии — из уже загруженного объекта списка, отдельного запроса
 * нет. Telegram BackButton и видимая кнопка "← Назад" вызывают один и тот
 * же onBack (единая навигация экрана, не вторая система). */
export function JournalV2Detail({
  initDataRaw, session, timeZone, onBack, onDeleted, onEdited, onCloned, onOpenWorkout, initialMode = "view",
}: {
  initDataRaw: string;
  session: SessionResponseV2;
  timeZone: string;
  onBack: () => void;
  onDeleted: (sessionId: number) => void;
  /** Запись изменена (#262) — экран перезагружает Журнал. */
  onEdited: () => void;
  /** Создан клон на дату "YYYY-MM-DD" (#262). */
  onCloned: (date: string) => void;
  /** «Открыть тренировку» (#281) — Workout Detail тренировки, из которой выполнена запись. */
  onOpenWorkout?: (workoutId: number) => void;
  /** Шторка записи (#280) открывает сразу форму «Изменить»/«Повторить»; отмена тогда ведёт обратно в Журнал. */
  initialMode?: "view" | "edit" | "clone";
}) {
  const [mode, setMode] = useState<"view" | "edit" | "clone">(initialMode);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const deleteInFlight = useRef(false);

  const leaveForm = initialMode === "view" ? () => setMode("view") : onBack;
  useBackButton(mode === "view" ? onBack : leaveForm, [mode, onBack]);

  async function handleDelete() {
    if (deleteInFlight.current) {
      return; // двойной клик
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

  if (mode === "edit") {
    return (
      <JournalV2EditForm
        initDataRaw={initDataRaw} session={session} timeZone={timeZone}
        onCancel={leaveForm} onSaved={onEdited}
      />
    );
  }
  if (mode === "clone") {
    return (
      <JournalV2CloneForm
        initDataRaw={initDataRaw} session={session} timeZone={timeZone}
        onCancel={leaveForm} onCloned={onCloned}
      />
    );
  }

  return (
    <div>
      {/* Круглая кнопка-шеврон; имя для скринридеров/тестов — «← Назад», тот же onBack, что у Telegram BackButton. */}
      <button type="button" className="journal-back-button" aria-label="← Назад" onClick={onBack}>
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
          <path d="M15 5l-7 7 7 7" />
        </svg>
      </button>
      <p className="plan-title">{session.title ?? "Тренировка"}</p>
      <p className="history-date">{formatSessionDateTime(session.performed_at, timeZone)}</p>
      {session.duration_seconds != null && (
        <p className="block-subtitle" data-testid="journal-activity-duration">Длительность: {formatDurationHm(session.duration_seconds)}</p>
      )}

      {session.blocks.map((block) => {
        const view = describeJournalBlock(block);
        return (
          <Section key={block.order_index} className="block-section" header={view.header ?? "Упражнение"}>
            {view.protocolLabel !== null && <p className="block-subtitle journal-detail-line">{view.protocolLabel}</p>}
            {view.plan !== null && <p className="journal-detail-line">План: {view.plan}</p>}
            <p className="journal-detail-line">Факт: {view.fact}</p>
            {block.set_logs.filter((log) => log.effort !== null || log.note).map((log) => (
              <p key={log.set_number} className="hint journal-detail-line">
                Подход {log.set_number}
                {log.effort !== null && ` · усилие ${effortWithWord(log.effort)}`}
                {log.note && ` · ${log.note}`}
              </p>
            ))}
          </Section>
        );
      })}

      {session.effort !== null && (
        <p className="block-subtitle" data-testid="journal-workout-effort">Усилие: {effortWithWord(session.effort)}</p>
      )}
      {session.comment && <p className="hint" data-testid="journal-workout-comment">Комментарий: {session.comment}</p>}
      {deleteError !== null && <p className="gap-banner">{deleteError}</p>}
      {onOpenWorkout && session.workout_id != null && (
        <Button
          className="action-button" size="l" stretched mode="outline" data-testid="journal-open-workout"
          onClick={() => onOpenWorkout(session.workout_id as number)}
        >
          Открыть тренировку
        </Button>
      )}
      {session.can_edit && (
        <>
          <Button className="action-button" size="l" stretched mode="outline" onClick={() => setMode("edit")}>
            ✏️ Изменить
          </Button>
          {session.source !== "elective" && (
            <Button className="action-button" size="l" stretched mode="outline" onClick={() => setMode("clone")}>
              ⧉ Повторить (клонировать)
            </Button>
          )}
        </>
      )}
      {session.can_delete && (
        <Button className="action-button" size="l" stretched mode="outline" loading={deleting} onClick={() => void handleDelete()}>
          🗑 Удалить
        </Button>
      )}
    </div>
  );
}
