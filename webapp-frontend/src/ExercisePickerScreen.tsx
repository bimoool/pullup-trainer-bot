import { Spinner } from "@telegram-apps/telegram-ui";
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

  const trimmed = query.trim();
  const exactMatch = state.phase === "ready" && state.exercises.some((exercise) => exercise.name.toLowerCase() === trimmed.toLowerCase());

  async function createFromQuery(name: string) {
    setCreateError(null);
    try {
      onSelect(await createExercise(initDataRaw, name));
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <div className="ux-form">
      <h2 className="plan-title">Добавить упражнение</h2>
      <p className="ux-helper">Выберите упражнение — на следующем шаге настроите подходы и отдых. Нет нужного? Введите название, и появится «Создать своё».</p>

      <input
        className="ux-text-input"
        type="search"
        aria-label="Поиск упражнения"
        placeholder="Поиск упражнения"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />

      {state.phase === "loading" && <Spinner size="m" />}
      {state.phase === "error" && <p className="gap-banner">Не удалось загрузить: {state.message}</p>}
      {state.phase === "ready" && (
        <div className="ux-pick-list" role="list">
          {filtered.map((exercise) => (
            <button key={exercise.id} type="button" role="listitem" className="ux-pick" onClick={() => onSelect(exercise)}>
              <span>{exercise.name}</span>
              <span className="ux-chevron" aria-hidden="true">›</span>
            </button>
          ))}
          {filtered.length === 0 && <p className="ux-helper">Ничего не найдено</p>}
          {trimmed !== "" && !exactMatch && (
            <button type="button" className="ux-pick ux-pick-create" onClick={() => void createFromQuery(trimmed)}>
              <span>Создать своё: «{trimmed}»</span>
              <span className="ux-chevron" aria-hidden="true">+</span>
            </button>
          )}
        </div>
      )}
      {createError && <p className="gap-banner">Не удалось создать: {createError}</p>}
    </div>
  );
}
