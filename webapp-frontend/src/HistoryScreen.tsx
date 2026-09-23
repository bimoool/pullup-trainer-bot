import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { deleteHistoryWorkout, fetchHistory, type HistoryEntry } from "./api";
import { fetchSessions, type SessionResponseV2 } from "./apiV2";
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

/** Checkpoint 4C (issue #188) — performed_at v2-сессии полная ISO-дата со
 * временем (не только "YYYY-MM-DD", как у legacy HistoryEntry), берём
 * только дату той жеформы "ДД.ММ.ГГГГ", день уже фиксирован сервером. */
function formatSessionDate(isoDateTime: string): string {
  return formatDate(isoDateTime.slice(0, 10));
}

export function HistoryScreen({ initDataRaw }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
  const [editingWorkoutId, setEditingWorkoutId] = useState<number | null>(null);
  const [deletingWorkoutId, setDeletingWorkoutId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  // Checkpoint 4C (issue #188) — combined Journal: completed TrainingSession
  // (новая схема) поверх legacy Workout ниже, обе модели остаются разными,
  // не сливаются в общий список и не портят HistoryEntry-контракт legacy
  // (раздел 2 задачи — не заполнять equipment_a/result_a и т.п. для
  // TrainingSession). Отдельный эффект/состояние — сбой этой секции не
  // должен ронять уже рабочую legacy-историю.
  const [v2Sessions, setV2Sessions] = useState<SessionResponseV2[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchSessions(initDataRaw, 50, "completed")
      .then((sessions) => {
        if (!cancelled) {
          setV2Sessions(sessions);
        }
      })
      .catch(() => {
        // молчаливо — секция новых тренировок просто не появится, legacy
        // ниже продолжает работать независимо (см. комментарий у стейта).
        if (!cancelled) {
          setV2Sessions([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

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

  if (state.phase === "loading") {
    return <p className="screen-message">Загружаю историю…</p>;
  }
  if (state.phase === "error") {
    return <p className="screen-message">Не удалось загрузить историю: {state.message}</p>;
  }
  const hasV2Sessions = v2Sessions !== null && v2Sessions.length > 0;
  if (state.items.length === 0 && !hasV2Sessions && v2Sessions !== null) {
    return <p className="screen-message">Пока нет ни одной тренировки.</p>;
  }

  return (
    <div>
      {/* Заголовок переименован в "Журнал" вслед за вкладкой нижнего меню
          (issue #183, волна 5b) — само содержимое экрана не менялось. */}
      <p className="plan-title">Журнал</p>
      {deleteError && <p className="screen-message">Не удалось удалить тренировку: {deleteError}</p>}

      {hasV2Sessions && (
        <div className="history-list">
          {v2Sessions?.map((session) => {
            // Phase B2 (issue #215, раздел 18) — узкая interval-ветка, не
            // Journal redesign: completed interval session показывает то
            // же минимальное summary, что и SessionSummaryScreen, не
            // SetLog rows/fake targets/Упражнение #id.
            const intervalResult = session.blocks.length > 0
              && typeof session.blocks[0].result === "object" && session.blocks[0].result !== null
              && (session.blocks[0].result as { type?: unknown }).type === "interval"
              ? session.blocks[0].result as {
                  actual_duration_seconds: number; completed_cycles: number;
                }
              : null;
            return (
              <div className="history-card" key={`v2-${session.id}`}>
                <p className="history-date">{formatSessionDate(session.performed_at)}</p>
                <p className="block-subtitle">{session.title ?? "Тренировка"}</p>
                {intervalResult !== null ? (
                  <p>
                    {Math.floor(intervalResult.actual_duration_seconds / 60)}:
                    {String(intervalResult.actual_duration_seconds % 60).padStart(2, "0")}
                    {" · "}{intervalResult.completed_cycles} интервалов
                  </p>
                ) : (
                  session.blocks.map((block) => (
                    <p key={block.order_index}>
                      {block.set_logs.map((log) => `${log.value} ${log.unit}`).join(" / ")}
                    </p>
                  ))
                )}
              </div>
            );
          })}
        </div>
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
