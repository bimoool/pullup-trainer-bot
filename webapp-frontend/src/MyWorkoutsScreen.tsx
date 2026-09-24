import { Button, Section, Spinner } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { listWorkouts, type WorkoutResponseV2 } from "./apiV2";
import { useBackButton } from "./useBackButton";

type Props = {
  initDataRaw: string;
  onBack: () => void;
  onCreateWorkout: () => void;
  onOpenWorkout: (workoutId: number) => void;
  onAddToPlan: (workoutId: number, workoutTitle: string) => void;
};

type ListState =
  | { phase: "loading" }
  | { phase: "ready"; workouts: WorkoutResponseV2[] }
  | { phase: "error"; message: string };

/**
 * Phase C4a/C5a (issue #188) — «Мои тренировки», список user-owned
 * Workout поверх уже готового Phase C2 API (GET /workouts). C5a добавляет
 * «Добавить в план» на каждую карточку — не primary action, отдельная
 * кнопка рядом с открытием на редактирование, не вместо неё.
 */
export function MyWorkoutsScreen({ initDataRaw, onBack, onCreateWorkout, onOpenWorkout, onAddToPlan }: Props) {
  const [state, setState] = useState<ListState>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    listWorkouts(initDataRaw)
      .then((workouts) => {
        if (!cancelled) {
          setState({ phase: "ready", workouts });
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  useBackButton(onBack, [onBack]);

  return (
    <div>
      <p className="plan-title">Мои тренировки</p>

      <Button className="action-button" size="l" stretched onClick={onCreateWorkout}>
        Создать тренировку
      </Button>

      {state.phase === "loading" && <Spinner size="m" />}
      {state.phase === "error" && (
        <p className="gap-banner">Не удалось загрузить: {state.message}</p>
      )}
      {state.phase === "ready" && state.workouts.length === 0 && (
        <p className="screen-message">У вас пока нет своих тренировок</p>
      )}
      {state.phase === "ready" && state.workouts.length > 0 && (
        <Section className="block-section">
          {state.workouts.map((workout) => (
            <div key={workout.id} className="plan-week-day-group">
              <button
                type="button"
                className="program-card-button"
                onClick={() => onOpenWorkout(workout.id)}
              >
                {workout.title}
              </button>
              <Button size="s" onClick={() => onAddToPlan(workout.id, workout.title)}>
                Добавить в план
              </Button>
            </div>
          ))}
        </Section>
      )}
    </div>
  );
}
