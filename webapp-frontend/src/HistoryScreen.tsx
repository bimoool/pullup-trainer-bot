import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { deleteHistoryWorkout, fetchHistory, type HistoryEntry } from "./api";
import { HistoryEditForm } from "./HistoryEditForm";
import { JournalV2Cards, JournalV2Detail } from "./JournalV2";
import { useJournalV2 } from "./useJournalV2";

type Props = { initDataRaw: string };

const PAGE_SIZE = 20;

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; items: HistoryEntry[]; hasMore: boolean; loadingMore: boolean };

/** "2026-09-03" -> "03.09.2026" — тот же формат, что format_history_entry
 * бота (app/bot/handlers/history.py), без сдвига дня по локальному
 * часовому поясу браузера (день уже фиксирован сервером). */
function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-");
  return `${day}.${month}.${year}`;
}

export function HistoryScreen({ initDataRaw }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
  const [editingWorkoutId, setEditingWorkoutId] = useState<number | null>(null);
  const [deletingWorkoutId, setDeletingWorkoutId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  // Журнал v2 (R2): завершённые TrainingSession поверх legacy Workout ниже —
  // модели остаются разными и НЕ сливаются в одну хронологию. Состояние
  // (загруженные страницы) живёт здесь, выше экрана деталей: возврат из
  // деталей сохраняет уже загруженный Журнал. Сбой этой секции не роняет
  // legacy-историю ниже.
  const journal = useJournalV2(initDataRaw);
  const [detailSessionId, setDetailSessionId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const page = await fetchHistory(initDataRaw, 0, PAGE_SIZE);
        if (!cancelled) {
          setState({ phase: "ready", items: page.items, hasMore: page.has_more, loadingMore: false });
        }
      } catch (error) {
        if (!cancelled) {
          setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  async function reloadFirstPage() {
    try {
      const page = await fetchHistory(initDataRaw, 0, PAGE_SIZE);
      setState({ phase: "ready", items: page.items, hasMore: page.has_more, loadingMore: false });
    } catch (error) {
      setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
    }
  }

  async function loadMore() {
    if (state.phase !== "ready") {
      return;
    }
    setState({ ...state, loadingMore: true });
    try {
      const page = await fetchHistory(initDataRaw, state.items.length, PAGE_SIZE);
      setState({
        phase: "ready",
        items: [...state.items, ...page.items],
        hasMore: page.has_more,
        loadingMore: false,
      });
    } catch (error) {
      setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
    }
  }

  async function handleDelete(workoutId: number, isBackdated: boolean) {
    // Каскадные (обычные) тренировки удаляются с пересчётом цепочки целей
    // (issue #146, решение Кирилла — вариант A) — последствия серьёзнее,
    // чем для бэкдейта/свободных (там пересчитывать нечего), формулировка
    // предупреждает об этом явно, не только "нельзя отменить".
    const message = isBackdated
      ? "Удалить эту тренировку из истории? Отменить это будет нельзя."
      : "Удалить эту тренировку? Это пересчитает цели всех следующих тренировок. Отменить это будет нельзя.";
    if (!window.confirm(message)) {
      return;
    }
    setDeleteError(null);
    setDeletingWorkoutId(workoutId);
    try {
      await deleteHistoryWorkout(initDataRaw, workoutId);
      await reloadFirstPage();
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : String(error));
    } finally {
      setDeletingWorkoutId(null);
    }
  }

  if (editingWorkoutId !== null) {
    return (
      <HistoryEditForm
        initDataRaw={initDataRaw}
        workoutId={editingWorkoutId}
        onCancel={() => setEditingWorkoutId(null)}
        onDone={() => {
          setEditingWorkoutId(null);
          void reloadFirstPage();
        }}
      />
    );
  }

  const detailSession = detailSessionId !== null
    ? journal.state.phase === "ready" ? journal.state.items.find((item) => item.id === detailSessionId) ?? null : null
    : null;
  if (detailSession !== null) {
    return (
      <JournalV2Detail
        initDataRaw={initDataRaw}
        session={detailSession}
        onBack={() => setDetailSessionId(null)}
        onDeleted={(sessionId) => {
          journal.removeById(sessionId);
          setDetailSessionId(null);
        }}
      />
    );
  }

  if (state.phase === "loading") {
    return <p className="screen-message">Загружаю историю…</p>;
  }
  if (state.phase === "error") {
    return <p className="screen-message">Не удалось загрузить историю: {state.message}</p>;
  }
  const v2Items = journal.state.phase === "ready" ? journal.state.items : [];
  const hasV2Sessions = v2Items.length > 0;
  if (state.items.length === 0 && !hasV2Sessions && journal.state.phase !== "loading") {
    return <p className="screen-message">Пока нет ни одной тренировки.</p>;
  }

  return (
    <div>
      {/* Заголовок переименован в "Журнал" вслед за вкладкой нижнего меню
          (issue #183, волна 5b) — само содержимое экрана не менялось. */}
      <p className="plan-title">Журнал</p>
      {deleteError && <p className="screen-message">Не удалось удалить тренировку: {deleteError}</p>}

      {journal.state.phase === "error" && (
        <p className="screen-message">Не удалось загрузить новые тренировки: {journal.state.message}</p>
      )}
      {hasV2Sessions && (
        <JournalV2Cards
          sessions={v2Items}
          hasMore={journal.state.phase === "ready" && journal.state.hasMore}
          loadingMore={journal.loadingMore}
          moreError={journal.moreError}
          onLoadMore={() => void journal.loadMore()}
          onOpen={setDetailSessionId}
        />
      )}

      {state.items.length === 0 && hasV2Sessions ? null : (
      <div className="history-list">
        {state.items.map((entry) => (
          <div className="history-card" key={entry.workout_id}>
            <p className="history-date">
              {formatDate(entry.performed_at)}
              {entry.is_backdated && <span className="hint"> (задним числом)</span>}
            </p>
            <p>
              Объём ({entry.equipment_a.label}): {entry.result_a}
              {entry.target_a !== null && `, следующая цель ${entry.target_a}`}
            </p>
            <p>
              Сила ({entry.equipment_b.label}): {entry.result_b}
              {entry.target_b !== null && `, следующая цель ${entry.target_b}`}
            </p>
            {entry.comment && <p className="hint">Комментарий: {entry.comment}</p>}
            <div className="history-card-actions">
              {/* Внесённые не в цепочку (бэкдейт/свободные, is_backdated) тоже
                  редактируются (issue #106) — просто без пересчёта цели/каскада
                  на бэкенде (WorkoutRepository.edit_noncascade_workout), кнопка
                  одна для всех записей. */}
              <Button
                mode="outline"
                size="s"
                onClick={() => setEditingWorkoutId(entry.workout_id)}
              >
                ✏️ Изменить
              </Button>
              {/* Удаление (issue #146) — теперь и для каскадных тренировок
                  (решение Кирилла, вариант A: удаление пересчитывает цепочку
                  целей), не только бэкдейт/свободных — is_deletable
                  (HistoryEntry в api.ts) сейчас всегда true. */}
              {entry.is_deletable && (
                <Button
                  mode="outline"
                  size="s"
                  loading={deletingWorkoutId === entry.workout_id}
                  onClick={() => void handleDelete(entry.workout_id, entry.is_backdated)}
                >
                  🗑 Удалить
                </Button>
              )}
            </div>
          </div>
        ))}
      </div>
      )}

      {state.items.length > 0 && state.hasMore && (
        <Button mode="outline" size="m" stretched onClick={() => void loadMore()} loading={state.loadingMore}>
          Показать ещё
        </Button>
      )}
    </div>
  );
}
