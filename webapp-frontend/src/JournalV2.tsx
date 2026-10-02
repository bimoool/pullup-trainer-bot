import { Button, Section } from "@telegram-apps/telegram-ui";
import { useRef, useState } from "react";

import { deleteSession, type SessionResponseV2 } from "./apiV2";
import { effortWithWord } from "./effortScale";
import { describeJournalBlock, formatSessionDateTime, formatSessionTime } from "./journalFormat";
import { JOURNAL_KIND_LABELS, journalKind } from "./journalKind";
import { formatDurationHm } from "./journalLog";
import { JournalV2CloneForm, JournalV2EditForm } from "./JournalV2Edit";
import { useBackButton } from "./useBackButton";

/** Карточка завершённой TrainingSession (Журнал v2). Каждый блок сессии
 * рендерится независимо — ни один блок не определяет вид всей карточки. */
export function JournalSessionCard({
  session, onOpen,
}: {
  session: SessionResponseV2;
  onOpen: (sessionId: number) => void;
}) {
  const kind = journalKind(session);
  return (
    <div
      className="history-card history-card-clickable journal-card"
      data-kind={kind}
      role="button"
      tabIndex={0}
      onClick={() => onOpen(session.id)}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen(session.id);
        }
      }}
    >
      <span className="journal-card-marker" aria-hidden="true" data-testid="journal-kind-marker" />
      <div className="journal-card-body">
        {/* Компактная карточка: строка 1 — название + время, строка 2 — тип/длительность/блоки. */}
        <p className="journal-card-title">
          <span className="journal-card-name">{session.title ?? "Тренировка"}</span>
          <span className="journal-card-time">{formatSessionTime(session.performed_at)}</span>
        </p>
        <p className="journal-card-meta">
          {kind !== "plan" && <span className="journal-kind-label">{JOURNAL_KIND_LABELS[kind]}</span>}
          {session.duration_seconds != null && (
            <span data-testid="journal-activity-duration">Длительность: {formatDurationHm(session.duration_seconds)}</span>
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
  initDataRaw, session, timeZone, onBack, onDeleted, onEdited, onCloned, onOpenWorkout,
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
}) {
  const [mode, setMode] = useState<"view" | "edit" | "clone">("view");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const deleteInFlight = useRef(false);

  useBackButton(mode === "view" ? onBack : () => setMode("view"), [mode, onBack]);

  async function handleDelete() {
    if (deleteInFlight.current) {
      return; // двойной клик
    }
    if (!window.confirm("Удалить эту тренировку? Отменить это будет нельзя.")) {
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
        onCancel={() => setMode("view")} onSaved={onEdited}
      />
    );
  }
  if (mode === "clone") {
    return (
      <JournalV2CloneForm
        initDataRaw={initDataRaw} session={session} timeZone={timeZone}
        onCancel={() => setMode("view")} onCloned={onCloned}
      />
    );
  }

  return (
    <div>
      <Button className="action-button" size="m" mode="outline" onClick={onBack}>
        ← Назад
      </Button>
      <p className="plan-title">{session.title ?? "Тренировка"}</p>
      <p className="history-date">{formatSessionDateTime(session.performed_at)}</p>
      {session.duration_seconds != null && (
        <p className="block-subtitle" data-testid="journal-activity-duration">Длительность: {formatDurationHm(session.duration_seconds)}</p>
      )}

      {session.blocks.map((block) => {
        const view = describeJournalBlock(block);
        return (
          <Section key={block.order_index} className="block-section" header={view.header ?? "Упражнение"}>
            {view.protocolLabel !== null && <p className="block-subtitle">{view.protocolLabel}</p>}
            {view.plan !== null && <p>План: {view.plan}</p>}
            <p>Факт: {view.fact}</p>
            {block.set_logs.filter((log) => log.effort !== null || log.note).map((log) => (
              <p key={log.set_number} className="hint">
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
