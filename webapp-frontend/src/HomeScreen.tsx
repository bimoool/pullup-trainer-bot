import { Button, Section } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  createProgramInclusion, fetchPlan, fetchPrograms, listWorkouts,
  type ProgramResponseV2, type WorkoutResponseV2,
} from "./apiV2";
import { AddToPlanScreen } from "./AddToPlanScreen";
import { ProgramDetailScreen } from "./ProgramDetailScreen";
import { WorkoutEditorScreen } from "./WorkoutEditorScreen";
import { formatExerciseCount, formatExerciseNames, formatFirstProtocol } from "./workoutCardFormat";

type Props = {
  initDataRaw: string;
  /** После «Добавить в план» из карточки Workout — переход на вкладку «Планы»
   * (тот же результат, что у добавления из «Планов»). */
  onOpenPlans: () => void;
};

type WorkoutsState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; workouts: WorkoutResponseV2[] };

/** Локальный swap внутри вкладки — те же Builder-экраны, что и в «Планах»
 * (WorkoutEditorScreen / AddToPlanScreen), без второй архитектуры исполнения. */
type WorkoutView =
  | { kind: "closed" }
  | { kind: "create" }
  | { kind: "edit"; workoutId: number }
  | { kind: "add-to-plan"; workoutId: number; workoutTitle: string };

type CatalogState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; programs: ProgramResponseV2[]; includedProgramIds: Set<number> };

type AddState = { phase: "idle" } | { phase: "adding"; programId: number } | { phase: "error"; message: string };

/**
 * Стартовый экран Mini App — каталог программ (issue #205, Checkpoint 5B;
 * crimpd-reference skill: "Главная = каталог программ / вход в Program Detail").
 * Home не дублирует Plans/Analytics/workout controls — только каталог, состояние
 * "В плане", переход в Program Detail. Полная сводка (статус готовности,
 * кнопка "Начать тренировку") на "Планах" (DashboardScreen.tsx).
 */
export function HomeScreen({ initDataRaw, onOpenPlans }: Props) {
  const [catalog, setCatalog] = useState<CatalogState>({ phase: "loading" });
  const [addState, setAddState] = useState<AddState>({ phase: "idle" });
  // Program Detail (issue #192) — тот же приём "swap внутри вкладки", что
  // showAchievements в ProfileScreen: id, не boolean, чтобы Detail-экран мог
  // прочитать конкретную карточку каталога.
  const [selectedProgramId, setSelectedProgramId] = useState<number | null>(null);
  // «Мои тренировки» грузятся отдельно от каталога: их сбой не ломает Программы.
  const [workouts, setWorkouts] = useState<WorkoutsState>({ phase: "loading" });
  const [workoutView, setWorkoutView] = useState<WorkoutView>({ kind: "closed" });
  const [workoutsReloadKey, setWorkoutsReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    listWorkouts(initDataRaw)
      .then((list) => {
        if (!cancelled) {
          setWorkouts({ phase: "ready", workouts: list });
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setWorkouts({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw, workoutsReloadKey]);

  function closeWorkoutView() {
    setWorkoutView({ kind: "closed" });
    setWorkoutsReloadKey((key) => key + 1);
  }

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchPrograms(initDataRaw), fetchPlan(initDataRaw)])
      .then(([programs, plan]) => {
        if (cancelled) {
          return;
        }
        const includedProgramIds = new Set(
          (plan?.program_inclusions ?? []).filter((i) => i.is_active).map((i) => i.program_id),
        );
        setCatalog({ phase: "ready", programs, includedProgramIds });
      })
      .catch((error) => {
        if (!cancelled) {
          setCatalog({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  async function handleAddToPlan(programId: number) {
    // Guard against duplicate in-flight requests (issue #211, HA-3: double-tap
    // protection). Error state intentionally NOT blocked — single intentional
    // click after error clears it and retries (тот же UX-паттерн, что
    // startingGroupKey в DashboardScreen.tsx::renderGroupRow).
    if (addState.phase === "adding") {
      return;
    }
    setAddState({ phase: "adding", programId });
    try {
      await createProgramInclusion(initDataRaw, programId);
      setCatalog((prev) =>
        prev.phase === "ready"
          ? { ...prev, includedProgramIds: new Set(prev.includedProgramIds).add(programId) }
          : prev,
      );
      setAddState({ phase: "idle" });
    } catch (error) {
      setAddState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
    }
  }

  if (workoutView.kind === "create") {
    return (
      <WorkoutEditorScreen
        key="create"
        initDataRaw={initDataRaw}
        workoutId={null}
        onBack={closeWorkoutView}
        onSaved={(workoutId) => setWorkoutView({ kind: "edit", workoutId })}
        onAddToPlan={() => {}}
      />
    );
  }
  if (workoutView.kind === "edit") {
    return (
      <WorkoutEditorScreen
        key={`edit-${workoutView.workoutId}`}
        initDataRaw={initDataRaw}
        workoutId={workoutView.workoutId}
        onBack={closeWorkoutView}
        onSaved={closeWorkoutView}
        onAddToPlan={(workoutId, workoutTitle) => setWorkoutView({ kind: "add-to-plan", workoutId, workoutTitle })}
      />
    );
  }
  if (workoutView.kind === "add-to-plan") {
    return (
      <AddToPlanScreen
        initDataRaw={initDataRaw}
        workoutId={workoutView.workoutId}
        workoutTitle={workoutView.workoutTitle}
        onBack={() => setWorkoutView({ kind: "edit", workoutId: workoutView.workoutId })}
        onSuccess={onOpenPlans}
      />
    );
  }

  if (selectedProgramId !== null && catalog.phase === "ready") {
    const program = catalog.programs.find((p) => p.id === selectedProgramId);
    if (program) {
      const included = catalog.includedProgramIds.has(program.id);
      const adding = addState.phase === "adding" && addState.programId === program.id;
      return (
        <ProgramDetailScreen
          program={program}
          included={included}
          adding={adding}
          addError={addState.phase === "error" ? addState.message : null}
          onAdd={() => void handleAddToPlan(program.id)}
          onBack={() => setSelectedProgramId(null)}
        />
      );
    }
  }

  return (
    <div>
      <p className="plan-title">Главная</p>

      <p className="section-title">Курсы</p>
      {/* Capability A (issue #188) — минимальный каталог: одна карточка на
          seed-программу, без категорий/поиска/уровней (это остаток волны 6).
          Issue #192 — карточка сама больше не выполняет действие, тап ведёт
          на отдельный Program Detail (ProgramDetailScreen.tsx), туда же
          переехала кнопка "Добавить в план"/"В плане ✓"; здесь остаётся
          только статус — краткий текст, не кнопка. */}
      {catalog.phase === "loading" && <p className="screen-message">Загружаю каталог…</p>}
      {catalog.phase === "error" && <p className="screen-message">Не удалось загрузить каталог: {catalog.message}</p>}
      {catalog.phase === "ready" && catalog.programs.length === 0 && (
        <p className="screen-message">Каталог курсов появится здесь позже.</p>
      )}
      {catalog.phase === "ready" && (
        <div className="home-program-row" data-testid="program-row">
        {catalog.programs.map((program) => {
          const included = catalog.includedProgramIds.has(program.id);
          return (
            <Section key={program.id} className="block-section home-program-card">
              <button
                type="button"
                className="program-card-button"
                onClick={() => setSelectedProgramId(program.id)}
              >
                <p className="block-subtitle">{program.name}</p>
                <p className="screen-message">{program.goal}</p>
                {included && <p className="hint">✓ В плане</p>}
              </button>
            </Section>
          );
        })}
        </div>
      )}

      <div className="home-section-header">
        <p className="section-title">Мои тренировки</p>
        {workouts.phase === "ready" && workouts.workouts.length > 0 && (
          <Button size="s" onClick={() => setWorkoutView({ kind: "create" })}>
            Создать
          </Button>
        )}
      </div>
      {workouts.phase === "loading" && <p className="screen-message">Загружаю тренировки…</p>}
      {workouts.phase === "error" && (
        <p className="screen-message">Не удалось загрузить тренировки: {workouts.message}</p>
      )}
      {workouts.phase === "ready" && workouts.workouts.length === 0 && (
        <>
          <p className="screen-message">Соберите свою тренировку из упражнений и протоколов.</p>
          <Button size="m" stretched onClick={() => setWorkoutView({ kind: "create" })}>
            Создать тренировку
          </Button>
        </>
      )}
      {workouts.phase === "ready" && workouts.workouts.length > 0 && (
        <ul className="home-workout-list" data-testid="my-workouts">
          {workouts.workouts.map((workout) => {
            const items = workout.items ?? [];
            const names = formatExerciseNames(items);
            const protocol = formatFirstProtocol(items);
            return (
              <li key={workout.id}>
                <button
                  type="button"
                  className="home-workout-card"
                  data-testid="my-workout-card"
                  onClick={() => setWorkoutView({ kind: "edit", workoutId: workout.id })}
                >
                  <span className="home-workout-title">{workout.title}</span>
                  <span className="home-workout-meta">
                    {items.length === 0 ? "Пока без упражнений" : formatExerciseCount(items.length)}
                    {protocol ? ` · ${protocol}` : ""}
                  </span>
                  {names && <span className="home-workout-names">{names}</span>}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
