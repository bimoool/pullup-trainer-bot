import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchHistory, type HistoryEntry } from "./api";
import { BackdateForm } from "./BackdateForm";
import { HistoryEditForm } from "./HistoryEditForm";

type Props = { initDataRaw: string };

const PAGE_SIZE = 20;

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; items: HistoryEntry[]; hasMore: boolean; loadingMore: boolean };

// Кроме самой ленты (ScreenState выше) — режим экрана поверх неё (issue
// #52, волна 2): кнопка редактирования на карточке и "Добавить за дату"
// временно подменяют ленту формой, а не уводят на отдельную вкладку (тот
// же принцип, что и anomaly_confirm в WorkoutScreen.tsx — состояние внутри
// одного компонента, не роутинг).
type Mode = { kind: "list" } | { kind: "edit"; workoutId: number } | { kind: "backdate" };

/** "2026-09-03" -> "03.09.2026" — тот же формат, что format_history_entry
 * бота (app/bot/handlers/history.py), без сдвига дня по локальному
 * часовому поясу браузера (день уже фиксирован сервером). */
function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-");
  return `${day}.${month}.${year}`;
}

export function HistoryScreen({ initDataRaw }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
  const [mode, setMode] = useState<Mode>({ kind: "list" });

  async function reload() {
    setState({ phase: "loading" });
    try {
      const page = await fetchHistory(initDataRaw, 0, PAGE_SIZE);
      setState({ phase: "ready", items: page.items, hasMore: page.has_more, loadingMore: false });
    } catch (error) {
      setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
    }
  }

  useEffect(() => {
    void reload();
  }, [initDataRaw]);

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

  // Успешное сохранение (правка или бэкдейт) возвращает к ленте и
  // перезагружает её с первой страницы — простой способ увидеть
  // актуальные target_a/target_b без ручного пересчёта на клиенте (тот же
  // WorkoutRepository.list_for_user, что и при первой загрузке).
  function handleSaved() {
    setMode({ kind: "list" });
    void reload();
  }

  if (mode.kind === "edit") {
    return (
      <HistoryEditForm
        initDataRaw={initDataRaw}
        workoutId={mode.workoutId}
        onCancel={() => setMode({ kind: "list" })}
        onSaved={handleSaved}
      />
    );
  }
  if (mode.kind === "backdate") {
    return <BackdateForm initDataRaw={initDataRaw} onCancel={() => setMode({ kind: "list" })} onSaved={handleSaved} />;
  }

  if (state.phase === "loading") {
    return <p className="screen-message">Загружаю историю…</p>;
  }
  if (state.phase === "error") {
    return <p className="screen-message">Не удалось загрузить историю: {state.message}</p>;
  }

  return (
    <div>
      <p className="plan-title">История</p>

      <Button className="action-button" size="m" stretched onClick={() => setMode({ kind: "backdate" })}>
        Добавить за дату
      </Button>

      {state.items.length === 0 && <p className="screen-message">Пока нет ни одной тренировки.</p>}

      <div className="history-list">
        {state.items.map((entry, index) => (
          <div className="history-card" key={`${entry.performed_at}-${index}`}>
            <div className="history-date-row">
              <p className="history-date">
                {formatDate(entry.performed_at)}
                {entry.is_backdated && <span className="hint"> (задним числом)</span>}
              </p>
              {!entry.is_backdated && (
                <Button
                  mode="plain"
                  size="s"
                  className="history-edit-button"
                  onClick={() => setMode({ kind: "edit", workoutId: entry.workout_id })}
                >
                  Изменить
                </Button>
              )}
            </div>
            <p>
              Объём ({entry.equipment_a.label}): {entry.result_a}
              {entry.target_a !== null && `, следующая цель ${entry.target_a}`}
            </p>
            <p>
              Сила ({entry.equipment_b.label}): {entry.result_b}
              {entry.target_b !== null && `, следующая цель ${entry.target_b}`}
            </p>
            {entry.comment && <p className="hint">Комментарий: {entry.comment}</p>}
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
