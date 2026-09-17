import { Button, Cell, Placeholder, Section, Spinner } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { deleteHistoryWorkout, fetchHistory, type HistoryEntry } from "./api";
import { HistoryEditForm } from "./HistoryEditForm";

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

/** `Section`+`Cell`/`Placeholder` вместо `.history-list`/`.history-card`/
 * `.screen-message` (issue #142) — тот же базовый паттерн, что
 * AchievementsScreen.tsx. Действия (✏️ Изменить/🗑 Удалить) — в `after`
 * ячейки, одной колонкой, вместо отдельного ряда кнопок под текстом
 * (`.history-card-actions` в index.css переиспользован для их раскладки). */
export function HistoryScreen({ initDataRaw }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
  const [editingWorkoutId, setEditingWorkoutId] = useState<number | null>(null);
  const [deletingWorkoutId, setDeletingWorkoutId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

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

  async function handleDelete(workoutId: number) {
    if (!window.confirm("Удалить эту тренировку из истории? Отменить это будет нельзя.")) {
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

  if (state.phase === "loading") {
    return (
      <Placeholder>
        <Spinner size="m" />
      </Placeholder>
    );
  }
  if (state.phase === "error") {
    return <Placeholder description={`Не удалось загрузить историю: ${state.message}`} />;
  }
  if (state.items.length === 0) {
    return <Placeholder description="Пока нет ни одной тренировки." />;
  }

  return (
    <div>
      {deleteError && <Placeholder description={`Не удалось удалить тренировку: ${deleteError}`} />}

      <Section header="История">
        {state.items.map((entry) => (
          <Cell
            key={entry.workout_id}
            subhead={`${formatDate(entry.performed_at)}${entry.is_backdated ? " (задним числом)" : ""}`}
            subtitle={`Сила (${entry.equipment_b.label}): ${entry.result_b}${
              entry.target_b !== null ? `, следующая цель ${entry.target_b}` : ""
            }`}
            description={entry.comment ? `Комментарий: ${entry.comment}` : undefined}
            multiline
            after={
              <div className="history-card-actions">
                {/* Внесённые не в цепочку (бэкдейт/свободные, is_backdated) тоже
                    редактируются (issue #106) — просто без пересчёта цели/каскада
                    на бэкенде (WorkoutRepository.edit_noncascade_workout), кнопка
                    одна для всех записей. */}
                <Button mode="outline" size="s" onClick={() => setEditingWorkoutId(entry.workout_id)}>
                  ✏️ Изменить
                </Button>
                {/* Удаление (issue #146) — только для записей вне каскада
                    (is_deletable). Обычные тренировки цепочки каскада пока не
                    удаляются вообще (см. HistoryEntry.is_deletable в api.ts) —
                    кнопка не показывается, не показывается disabled без
                    объяснения. */}
                {entry.is_deletable && (
                  <Button
                    mode="outline"
                    size="s"
                    loading={deletingWorkoutId === entry.workout_id}
                    onClick={() => void handleDelete(entry.workout_id)}
                  >
                    🗑 Удалить
                  </Button>
                )}
              </div>
            }
          >
            {`Объём (${entry.equipment_a.label}): ${entry.result_a}${
              entry.target_a !== null ? `, следующая цель ${entry.target_a}` : ""
            }`}
          </Cell>
        ))}
      </Section>

      {state.hasMore && (
        <Button mode="outline" size="m" stretched onClick={() => void loadMore()} loading={state.loadingMore}>
          Показать ещё
        </Button>
      )}
    </div>
  );
}
