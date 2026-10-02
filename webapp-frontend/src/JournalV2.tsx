import { Button, Section } from "@telegram-apps/telegram-ui";
import { useRef, useState } from "react";

import { deleteSession, type SessionResponseV2 } from "./apiV2";
import { effortWithWord } from "./effortScale";
import { describeJournalBlock, formatSessionDateTime } from "./journalFormat";
import { formatDurationHm } from "./journalLog";
import { useBackButton } from "./useBackButton";

/** Карточка завершённой TrainingSession (Журнал v2). Каждый блок сессии
 * рендерится независимо — ни один блок не определяет вид всей карточки. */
export function JournalSessionCard({
  session, onOpen,
}: {
  session: SessionResponseV2;
  onOpen: (sessionId: number) => void;
}) {
  return (
    <div
      className="history-card history-card-clickable"
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
      <p className="history-date">{formatSessionDateTime(session.performed_at)}</p>
      <p className="block-subtitle">{session.title ?? "Тренировка"}</p>
      {session.duration_seconds != null && (
        <p data-testid="journal-activity-duration">Длительность: {formatDurationHm(session.duration_seconds)}</p>
      )}
      {session.source === "backdated" && <p className="hint">Записана задним числом</p>}
      {session.blocks.map((block) => {
        const view = describeJournalBlock(block);
        return (
          <div key={block.order_index} className="journal-block">
            {view.header !== null && <p className="journal-block-header">{view.header}</p>}
            <p>{view.fact}</p>
          </div>
        );
      })}
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
  initDataRaw, session, onBack, onDeleted,
}: {
  initDataRaw: string;
  session: SessionResponseV2;
  onBack: () => void;
  onDeleted: (sessionId: number) => void;
}) {
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const deleteInFlight = useRef(false);

  useBackButton(onBack, [onBack]);

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
      {session.can_delete && (
        <Button className="action-button" size="l" stretched mode="outline" loading={deleting} onClick={() => void handleDelete()}>
          🗑 Удалить
        </Button>
      )}
    </div>
  );
}
