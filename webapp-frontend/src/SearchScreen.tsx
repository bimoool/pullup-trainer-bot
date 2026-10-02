import { useEffect, useMemo, useRef, useState } from "react";

import {
  fetchExercises, fetchPrograms, listAssessments, listFavorites, listWorkouts,
  type AssessmentProtocolV2, type ExerciseResponseV2, type FavoriteV2, type ProgramResponseV2, type WorkoutResponseV2,
} from "./apiV2";
import { formatLastResult } from "./assessmentsFormat";
import { collectCategories, searchContent, toggleSearchFilter } from "./homeDiscovery";
import { useBackButton } from "./useBackButton";

export type SearchState = { query: string; category: string | null; favoritesOnly: boolean; testsOnly: boolean };

type Props = {
  initDataRaw: string;
  state: SearchState;
  onStateChange: (state: SearchState) => void;
  onClose: () => void;
  onOpenProgram: (programId: number) => void;
  onOpenWorkout: (workoutId: number) => void;
  onOpenExercise: (exerciseId: number, name: string) => void;
  /** Результат-тест → детали теста (#281, D6). */
  onOpenTest: (protocolId: number) => void;
};

type Data = {
  programs: ProgramResponseV2[]; workouts: WorkoutResponseV2[]; exercises: ExerciseResponseV2[]; favorites: FavoriteV2[];
  assessments: AssessmentProtocolV2[];
};
type LoadState = { phase: "loading" } | { phase: "error"; message: string } | { phase: "ready"; data: Data };

/**
 * Экран поиска Главной (issue #254): живая клиентская фильтрация по реальному
 * контенту — программы, свои тренировки, библиотечные упражнения. Чипы
 * категорий строятся из `category` загруженных данных (без хардкода).
 */
export function SearchScreen({
  initDataRaw, state, onStateChange, onClose, onOpenProgram, onOpenWorkout, onOpenExercise, onOpenTest,
}: Props) {
  const [load, setLoad] = useState<LoadState>({ phase: "loading" });
  const inputRef = useRef<HTMLInputElement>(null);

  useBackButton(onClose, [onClose]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchPrograms(initDataRaw), listWorkouts(initDataRaw), fetchExercises(initDataRaw), listFavorites(initDataRaw),
      // Тесты — необязательная группа: их сбой не ломает остальной поиск.
      listAssessments(initDataRaw).catch((): AssessmentProtocolV2[] => []),
    ])
      .then(([programs, workouts, exercises, favorites, assessments]) => {
        if (!cancelled) {
          setLoad({ phase: "ready", data: { programs, workouts, exercises, favorites, assessments } });
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setLoad({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  const data = load.phase === "ready" ? load.data : null;
  const categories = useMemo(
    () => (data ? collectCategories(data.programs, data.exercises) : []),
    [data],
  );
  const results = useMemo(
    () => (data ? searchContent(data, state.query, state.category, state.favoritesOnly ? data.favorites : null, state.testsOnly) : null),
    [data, state.query, state.category, state.favoritesOnly, state.testsOnly],
  );

  return (
    <div className="search-screen" data-testid="search-screen">
      <div className="search-header">
        <input
          ref={inputRef}
          className="search-input"
          type="search"
          placeholder="Что потренируем сегодня?"
          aria-label="Поиск"
          value={state.query}
          onChange={(event) => onStateChange({ ...state, query: event.target.value })}
        />
        <button type="button" className="search-close" onClick={onClose}>Закрыть</button>
      </div>

      {data && (
        <div className="search-chips" data-testid="search-chips">
          <button
            type="button"
            className={state.favoritesOnly ? "search-chip search-chip-active" : "search-chip"}
            data-testid="search-chip-favorites"
            aria-pressed={state.favoritesOnly}
            onClick={() => onStateChange(toggleSearchFilter(state, { kind: "favorites" }))}
          >
            Избранное
          </button>
          <button
            type="button"
            className={state.testsOnly ? "search-chip search-chip-active" : "search-chip"}
            data-testid="search-chip-tests"
            aria-pressed={state.testsOnly}
            onClick={() => onStateChange(toggleSearchFilter(state, { kind: "tests" }))}
          >
            Тесты
          </button>
          {categories.map((category) => (
            <button
              key={category}
              type="button"
              className={category === state.category ? "search-chip search-chip-active" : "search-chip"}
              aria-pressed={category === state.category}
              onClick={() => onStateChange(toggleSearchFilter(state, { kind: "category", category }))}
            >
              {category}
            </button>
          ))}
          {state.category !== null && (
            <button type="button" className="search-chip search-chip-clear" onClick={() => onStateChange({ ...state, category: null })}>
              Сбросить
            </button>
          )}
        </div>
      )}

      {load.phase === "loading" && <p className="screen-message">Загружаю…</p>}
      {load.phase === "error" && <p className="screen-message">Не удалось загрузить: {load.message}</p>}

      {results && (
        <>
          {state.category !== null && <p className="section-title" data-testid="search-category-title">{state.category}</p>}
          <p className="hint" data-testid="search-count">Найдено: {results.total}</p>
          {results.total === 0 && <p className="screen-message" data-testid="search-empty">Ничего не найдено</p>}

          {results.tests.length > 0 && (
            <>
              <p className="section-title">Тесты</p>
              <ul className="search-list">
                {results.tests.map((test) => (
                  <li key={`t${test.id}`}>
                    <button type="button" className="search-result" data-testid="search-result-test" onClick={() => onOpenTest(test.id)}>
                      <span className="home-workout-title">{test.name}</span>
                      <span className="home-workout-meta">{formatLastResult(test.last_result)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}

          {results.programs.length > 0 && (
            <>
              <p className="section-title">Программы</p>
              <ul className="search-list">
                {results.programs.map((program) => (
                  <li key={`p${program.id}`}>
                    <button type="button" className="search-result" data-testid="search-result-program" onClick={() => onOpenProgram(program.id)}>
                      <span className="home-workout-title">{program.name}</span>
                      <span className="home-workout-meta">{program.goal}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}

          {results.workouts.length > 0 && (
            <>
              <p className="section-title">Мои тренировки</p>
              <ul className="search-list">
                {results.workouts.map((workout) => (
                  <li key={`w${workout.id}`}>
                    <button type="button" className="search-result" data-testid="search-result-workout" onClick={() => onOpenWorkout(workout.id)}>
                      <span className="home-workout-title">{workout.title}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}

          {results.exercises.length > 0 && (
            <>
              <p className="section-title">Упражнения</p>
              <ul className="search-list">
                {results.exercises.map((exercise) => (
                  <li key={`e${exercise.id}`}>
                    <button type="button" className="search-result" data-testid="search-result-exercise" onClick={() => onOpenExercise(exercise.id, exercise.name)}>
                      <span className="home-workout-title">{exercise.name}</span>
                      <span className="home-workout-meta">{exercise.category}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </div>
  );
}
