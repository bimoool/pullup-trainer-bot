import { Spinner } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  getWorkout, listWorkoutSessions, type WorkoutResponseV2, type WorkoutSessionSummaryV2,
} from "./apiV2";
import { CategoryGlyph } from "./CategoryGlyph";
import { FavoriteHeart } from "./FavoriteHeart";
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
  /** «Начать»: живая сессия этой тренировки вне плана. */
  onStart?: (workoutId: number, workoutTitle: string) => void;
  /** «Записать»: форма записи задним числом с этой тренировкой. */
  onLog?: (workoutId: number) => void;
};

type DetailState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; workout: WorkoutResponseV2 };

type HistoryState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; sessions: WorkoutSessionSummaryV2[] };

function ActionIcon({ path, fill = false }: { path: string; fill?: boolean }) {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill={fill ? "currentColor" : "none"} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" focusable="false">
      <path d={path} />
    </svg>
  );
}

function ClockIcon() {
  return (
    <svg className="wd-clock" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" />
    </svg>
  );
}

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
export function WorkoutDetailScreen({ initDataRaw, workoutId, onBack, onEdit, onAddToPlan, onStart, onLog }: Props) {
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

  // Как в эталоне, на деталях нижней навигации нет: «назад» — кнопка в шапке и Telegram BackButton.
  useEffect(() => {
    const root = document.documentElement;
    root.classList.add("vp-nav-hidden");
    return () => root.classList.remove("vp-nav-hidden");
  }, []);

  if (detail.phase === "loading") {
    return <Spinner size="m" />;
  }
  if (detail.phase === "error") {
    return (
      <>
        <p className="gap-banner">Не удалось загрузить: {detail.message}</p>
        <button type="button" className="action-button" onClick={onBack}>← Назад</button>
      </>
    );
  }

  const { workout } = detail;
  const items = [...(workout.items ?? [])].sort((a, b) => a.order_index - b.order_index);
  const estimate = formatEstimate(estimateWorkoutSeconds(items));

  return (
    <div data-testid="workout-detail" className="workout-detail">
      <div className="wd-hero" data-testid="workout-detail-hero" style={{ ["--cat" as string]: "var(--vp-cat-0)" }}>
        <button type="button" className="wd-hero-back" aria-label="Назад" data-testid="workout-detail-back" onClick={onBack}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
            <path d="m15 5-7 7 7 7" />
          </svg>
        </button>
        <div className="wd-hero-fav">
          <FavoriteHeart initDataRaw={initDataRaw} targetType="workout" targetId={workout.id} />
        </div>
        <span className="wd-hero-badge" aria-hidden="true">
          <CategoryGlyph glyph="dumbbell" size={30} />
        </span>
      </div>

      <h1 className="plan-title wd-title" data-testid="workout-detail-title" title={workout.title}>{workout.title}</h1>
      <div className="wd-meta-row">
        <p className="hint" data-testid="workout-detail-subtitle">Своя тренировка</p>
        <p className="hint wd-duration-pill" data-testid="workout-detail-meta">
          {estimate && <ClockIcon />}
          {items.length === 0 ? "Пока без упражнений" : formatExerciseCount(items.length)}
          {estimate ? ` · ${estimate}` : ""}
        </p>
      </div>

      <div className="workout-detail-actions">
        {onStart && (
          <button
            type="button" className="workout-detail-action workout-detail-action-primary" data-testid="workout-detail-start"
            disabled={items.length === 0} onClick={() => onStart(workout.id, workout.title)}
          >
            <span className="workout-detail-action-icon" aria-hidden="true">
              <ActionIcon path="M8 5.5v13l10.5-6.5z" fill />
            </span>
            <span className="workout-detail-action-label">Начать</span>
          </button>
        )}
        {onLog && (
          <button
            type="button" className="workout-detail-action" data-testid="workout-detail-log"
            onClick={() => onLog(workout.id)}
          >
            <span className="workout-detail-action-icon" aria-hidden="true">
              <ActionIcon path="M9 4.5h6M8 6.5h8a1.5 1.5 0 0 1 1.5 1.5v11a1.5 1.5 0 0 1-1.5 1.5H8A1.5 1.5 0 0 1 6.5 19V8A1.5 1.5 0 0 1 8 6.5zM9.5 13.5l2 2 3.5-4" />
            </span>
            <span className="workout-detail-action-label">Записать</span>
          </button>
        )}
        <button
          type="button" className="workout-detail-action"
          onClick={() => onAddToPlan(workout.id, workout.title)}
        >
          <span className="workout-detail-action-icon" aria-hidden="true">
            <ActionIcon path="M12 5v14M5 12h14" />
          </span>
          <span className="workout-detail-action-label">Добавить в план</span>
        </button>
        {/* Видимая подпись короткая (в 4 колонки на 320 «Редактировать» не помещается), имя для AT и тестов — полное. */}
        <button type="button" className="workout-detail-action" aria-label="Редактировать" onClick={() => onEdit(workout.id)}>
          <span className="workout-detail-action-icon" aria-hidden="true">
            <ActionIcon path="M4.5 19.5l1-4L16 5l3 3-10.5 10.5zM14 7l3 3" />
          </span>
          <span className="workout-detail-action-label">Изменить</span>
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
