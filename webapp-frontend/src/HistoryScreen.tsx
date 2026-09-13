import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchHistory, type HistoryEntry } from "./api";
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

export function HistoryScreen({ initDataRaw }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
  const [editingWorkoutId, setEditingWorkoutId] = useState<number | null>(null);

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
    return <p className="screen-message">Загружаю историю…</p>;
  }
  if (state.phase === "error") {
    return <p className="screen-message">Не удалось загрузить историю: {state.message}</p>;
  }
  if (state.items.length === 0) {
    return <p className="screen-message">Пока нет ни одной тренировки.</p>;
  }

  return (
    <div>
      <p className="plan-title">История</p>

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
          </div>
        ))}
      </div>

      {state.hasMore && (
        <Button mode="outline" size="m" stretched onClick={() => void loadMore()} loading={state.loadingMore}>
          Показать ещё
        </Button>
      )}
    </div>
  );
}
