import { Button, Input, Section, Spinner } from "@telegram-apps/telegram-ui";
import { useEffect, useMemo, useState } from "react";

import { createExercise, type ExerciseResponseV2, fetchExercises } from "./apiV2";
import { useBackButton } from "./useBackButton";

type Props = {
  initDataRaw: string;
  onBack: () => void;
  onSelect: (exercise: ExerciseResponseV2) => void;
};

type ListState =
  | { phase: "loading" }
  | { phase: "ready"; exercises: ExerciseResponseV2[] }
  | { phase: "error"; message: string };

/**
 * Phase C4b-1 (issue #188) — Exercise Picker для Workout Builder,
 * отдельный от уже существующего picker'а в DashboardScreen.tsx (тот
 * встроен в конкретный PlanItem-flow, не был вынесен в переиспользуемый
 * компонент — не трогаю его в этом chunk). Использует уже готовый C1 API
 * (GET /exercises — system + свои user Exercise, чужие не видны;
 * POST /exercises — создание своего).
 */
export function ExercisePickerScreen({ initDataRaw, onBack, onSelect }: Props) {
  const [state, setState] = useState<ListState>({ phase: "loading" });
  const [query, setQuery] = useState("");
  const [creatingName, setCreatingName] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchExercises(initDataRaw)
      .then((exercises) => {
        if (!cancelled) {
          setState({ phase: "ready", exercises });
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

  const filtered = useMemo(() => {
    if (state.phase !== "ready") {
      return [];
    }
    const needle = query.trim().toLowerCase();
    if (needle === "") {
      return state.exercises;
    }
    return state.exercises.filter((exercise) => exercise.name.toLowerCase().includes(needle));
  }, [state, query]);

  async function handleCreateOwn() {
    const name = creatingName?.trim() ?? "";
    if (name === "") {
      return;
    }
    setCreateError(null);
    try {
      const created = await createExercise(initDataRaw, name);
      onSelect(created);
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <div>
      <p className="plan-title">Добавить упражнение</p>

      <Input
        placeholder="Поиск"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />

      {state.phase === "loading" && <Spinner size="m" />}
      {state.phase === "error" && (
        <p className="gap-banner">Не удалось загрузить: {state.message}</p>
      )}
      {state.phase === "ready" && (
        <Section className="block-section">
          {filtered.map((exercise) => (
            <button
              key={exercise.id}
              type="button"
              className="program-card-button"
              onClick={() => onSelect(exercise)}
            >
              {exercise.name}
            </button>
          ))}
          {filtered.length === 0 && <p className="screen-message">Ничего не найдено</p>}
        </Section>
      )}

      {creatingName === null ? (
        <Button className="action-button" size="m" stretched onClick={() => setCreatingName("")}>
          Создать своё упражнение
        </Button>
      ) : (
        <Section className="block-section">
          <Input
            header="Название"
            value={creatingName}
            onChange={(event) => setCreatingName(event.target.value)}
            placeholder="Название упражнения"
          />
          {createError && <p className="gap-banner">Не удалось создать: {createError}</p>}
          <Button
            className="action-button" size="m" stretched
            disabled={creatingName.trim().length === 0}
            onClick={() => void handleCreateOwn()}
          >
            Создать
          </Button>
        </Section>
      )}
    </div>
  );
}
