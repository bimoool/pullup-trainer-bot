import { Button, Section, Spinner } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { listWorkouts, type WorkoutResponseV2 } from "./apiV2";
import { useBackButton } from "./useBackButton";

type Props = {
  initDataRaw: string;
  onBack: () => void;
  onCreateWorkout: () => void;
  onOpenWorkout: (workoutId: number) => void;
};

type ListState =
  | { phase: "loading" }
  | { phase: "ready"; workouts: WorkoutResponseV2[] }
  | { phase: "error"; message: string };

/**
 * Phase C4a (issue #188) — «Мои тренировки», список user-owned Workout
 * поверх уже готового Phase C2 API (GET /workouts). Только list/empty-
 * state/entry points — item editor/Add to Plan/delete явно вне scope
 * этого chunk (следующие волны).
 */
export function MyWorkoutsScreen({ initDataRaw, onBack, onCreateWorkout, onOpenWorkout }: Props) {
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
            <button
              key={workout.id}
              type="button"
              className="program-card-button"
              onClick={() => onOpenWorkout(workout.id)}
            >
              {workout.title}
            </button>
          ))}
        </Section>
      )}
    </div>
  );
}
