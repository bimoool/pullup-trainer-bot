import { Spinner } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  getWorkout, listWorkoutSessions, type WorkoutResponseV2, type WorkoutSessionSummaryV2,
} from "./apiV2";
import { formatExerciseCount } from "./workoutCardFormat";
import {
  estimateWorkoutSeconds, formatEstimate, formatItemSummary, formatSetsDone,
} from "./workoutDetailFormat";
import { useBackButton } from "./useBackButton";

type Props = {
  initDataRaw: string;
  workoutId: number;
  onBack: () => void;
  onEdit: (workoutId: number) => void;
  onAddToPlan: (workoutId: number, workoutTitle: string) => void;
};

type DetailState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; workout: WorkoutResponseV2 };

type HistoryState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; sessions: WorkoutSessionSummaryV2[] };

function formatSessionDate(iso: string): string {
  const date = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()}`;
}

/**
 * Workout Detail (issue #255) — read-only карточка своей тренировки: сводка,
 * упражнения, «Добавить в план» / «Редактировать» и история выполнений. Это не
 * редактор: правки — только через существующий WorkoutEditorScreen.
 */
export function WorkoutDetailScreen({ initDataRaw, workoutId, onBack, onEdit, onAddToPlan }: Props) {
  const [detail, setDetail] = useState<DetailState>({ phase: "loading" });
  const [history, setHistory] = useState<HistoryState>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    const message = (error: unknown) => (error instanceof Error ? error.message : String(error));
    getWorkout(initDataRaw, workoutId)
      .then((workout) => !cancelled && setDetail({ phase: "ready", workout }))
      .catch((error) => !cancelled && setDetail({ phase: "error", message: message(error) }));
    listWorkoutSessions(initDataRaw, workoutId)
      .then((sessions) => !cancelled && setHistory({ phase: "ready", sessions }))
      .catch((error) => !cancelled && setHistory({ phase: "error", message: message(error) }));
    return () => {
      cancelled = true;
    };
  }, [initDataRaw, workoutId]);

  useBackButton(onBack, [onBack]);

  if (detail.phase === "loading") {
    return <Spinner size="m" />;
  }
  if (detail.phase === "error") {
    return <p className="gap-banner">Не удалось загрузить: {detail.message}</p>;
  }

  const { workout } = detail;
  const items = [...(workout.items ?? [])].sort((a, b) => a.order_index - b.order_index);
  const estimate = formatEstimate(estimateWorkoutSeconds(items));

  return (
    <div data-testid="workout-detail">
      <p className="plan-title" data-testid="workout-detail-title">{workout.title}</p>
      <p className="hint" data-testid="workout-detail-subtitle">Своя тренировка</p>
      <p className="hint" data-testid="workout-detail-meta">
        {items.length === 0 ? "Пока без упражнений" : formatExerciseCount(items.length)}
        {estimate ? ` · ${estimate}` : ""}
      </p>

      <div className="workout-detail-actions">
        <button
          type="button" className="workout-detail-action"
          onClick={() => onAddToPlan(workout.id, workout.title)}
        >
          <span className="workout-detail-action-icon" aria-hidden="true">＋</span>
          <span className="workout-detail-action-label">Добавить в план</span>
        </button>
        <button type="button" className="workout-detail-action" onClick={() => onEdit(workout.id)}>
          <span className="workout-detail-action-icon" aria-hidden="true">✎</span>
          <span className="workout-detail-action-label">Редактировать</span>
        </button>
      </div>

      <p className="section-title">Упражнения</p>
      {items.length === 0 ? (
        <p className="screen-message">В тренировке пока нет упражнений</p>
      ) : (
        <ul className="home-workout-list" data-testid="workout-detail-items">
          {items.map((item) => (
            <li key={item.id} className="workout-detail-item">
              <span className="home-workout-title">{item.exercise_name}</span>
              <span className="home-workout-meta" style={{ whiteSpace: "normal" }}>{formatItemSummary(item.protocol)}</span>
            </li>
          ))}
        </ul>
      )}

      <p className="section-title">История</p>
      {history.phase === "loading" && <Spinner size="m" />}
      {history.phase === "error" && <p className="gap-banner">Не удалось загрузить историю: {history.message}</p>}
      {history.phase === "ready" && history.sessions.length === 0 && (
        <p className="screen-message" data-testid="workout-detail-history-empty">Вы ещё не выполняли эту тренировку</p>
      )}
      {history.phase === "ready" && history.sessions.length > 0 && (
        <ul className="home-workout-list" data-testid="workout-detail-history">
          {history.sessions.map((session) => (
            <li key={session.id} className="workout-detail-item" data-testid="workout-detail-history-row">
              <span className="home-workout-title">{formatSessionDate(session.performed_at)}</span>
              <span className="home-workout-meta">
                {formatExerciseCount(session.exercises_count)} · {formatSetsDone(session.sets_done)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
