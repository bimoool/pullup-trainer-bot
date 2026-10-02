import { Button, Section } from "@telegram-apps/telegram-ui";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import {
  createProgramInclusion, fetchPlan, fetchPrograms, listFavorites, listWorkouts,
  type FavoriteV2, type ProgramResponseV2, type WorkoutResponseV2,
} from "./apiV2";
import { AddToPlanScreen } from "./AddToPlanScreen";
import { CollectionScreen } from "./CollectionScreen";
import { CollectionsRow } from "./CollectionsRow";
import { favoritesRowMode, markFavoritesSeen, readFavoritesSeen } from "./favorites";
import { groupProgramsByCategory, OTHER_CATEGORY } from "./homeDiscovery";
import { ProgramDetailScreen } from "./ProgramDetailScreen";
import { SearchScreen, type SearchState } from "./SearchScreen";
import { TestDetailScreen } from "./TestDetailScreen";
import { TestsScreen } from "./TestsScreen";
import { WorkoutDetailScreen } from "./WorkoutDetailScreen";
import { WorkoutEditorScreen } from "./WorkoutEditorScreen";
import { formatExerciseCount, formatExerciseNames, formatFirstProtocol } from "./workoutCardFormat";

type Props = {
  initDataRaw: string;
  /** После «Добавить в план» из карточки Workout — переход на вкладку «Планы»
   * (тот же результат, что у добавления из «Планов»). */
  onOpenPlans: () => void;
  /** «+» → «Записать в журнал»: открыть Журнал со шторкой записи (#263). */
  onOpenJournalLog: () => void;
  /** «Начать» на Workout Detail — живая сессия своей тренировки вне плана. */
  onStartWorkout: (workoutId: number, workoutTitle: string) => void;
  /** «Записать» на Workout Detail — Журнал с формой записи, заполненной этой тренировкой. */
  onLogWorkout: (workoutId: number) => void;
  /** Открыть сразу Workout Detail этой тренировки (из Журнала, #281); «назад» возвращает в Журнал. */
  initialWorkoutId?: number | null;
  onInitialWorkoutShown?: () => void;
  /** false — деталь открыта возвратом из «Записать» (#277): «назад» остаётся на Главной, не в Журнал. */
  initialWorkoutFromJournal?: boolean;
  onExitInitialWorkout?: () => void;
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
  | { kind: "detail"; workoutId: number }
  | { kind: "edit"; workoutId: number }
  | { kind: "add-to-plan"; workoutId: number; workoutTitle: string }
  | { kind: "add-exercise"; exerciseId: number; exerciseName: string };

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
export function HomeScreen({
  initDataRaw, onOpenPlans, onOpenJournalLog, onStartWorkout, onLogWorkout,
  initialWorkoutId = null, onInitialWorkoutShown, initialWorkoutFromJournal = true, onExitInitialWorkout,
}: Props) {
  const [catalog, setCatalog] = useState<CatalogState>({ phase: "loading" });
  const [addState, setAddState] = useState<AddState>({ phase: "idle" });
  // Program Detail (issue #192) — тот же приём "swap внутри вкладки", что
  // showAchievements в ProfileScreen: id, не boolean, чтобы Detail-экран мог
  // прочитать конкретную карточку каталога.
  const [selectedProgramId, setSelectedProgramId] = useState<number | null>(null);
  // «Мои тренировки» грузятся отдельно от каталога: их сбой не ломает Программы.
  const [workouts, setWorkouts] = useState<WorkoutsState>({ phase: "loading" });
  const [workoutView, setWorkoutView] = useState<WorkoutView>(
    initialWorkoutId !== null ? { kind: "detail", workoutId: initialWorkoutId } : { kind: "closed" },
  );
  // Пришли из Журнала: первое закрытие Workout Detail возвращает туда, а не на Главную.
  const exitToJournal = useRef(initialWorkoutId !== null && initialWorkoutFromJournal);
  useEffect(() => {
    if (initialWorkoutId !== null) {
      onInitialWorkoutShown?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- только при монтировании.
  }, []);
  const [workoutsReloadKey, setWorkoutsReloadKey] = useState(0);
  // Избранное (issue #272): null — ещё не загружено/не удалось (ряд тогда скрыт).
  const [favorites, setFavorites] = useState<FavoriteV2[] | null>(null);
  const [favoritesReloadKey, setFavoritesReloadKey] = useState(0);
  // Поиск (issue #254) и «+»-шторка. Поиск остаётся «открытым» под Program Detail /
  // редактором, чтобы «назад» оттуда возвращал в результаты, а не на Главную.
  const [searching, setSearching] = useState(false);
  const [searchState, setSearchState] = useState<SearchState>({ query: "", category: null, favoritesOnly: false, testsOnly: false });
  // Тест, открытый из результатов поиска (#281, D6): «назад» возвращает в поиск.
  const [searchTestId, setSearchTestId] = useState<number | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  // Хаб «Тесты» (#260) — локальный swap внутри вкладки, как Program/Workout Detail.
  const [showTests, setShowTests] = useState(false);
  // Подборка (#271): открытая подборка остаётся «под» Program Detail / «Добавить в план».
  const [collectionId, setCollectionId] = useState<number | null>(null);
  const savedScrollY = useRef<number | null>(null);

  useLayoutEffect(() => {
    if (!searching && savedScrollY.current !== null) {
      window.scrollTo(0, savedScrollY.current);
      savedScrollY.current = null;
    }
  }, [searching]);

  // category — «Все ›» у ряда категории (#281, H4): поиск, уже отфильтрованный по ней.
  function openSearch(category: string | null = null) {
    savedScrollY.current = window.scrollY;
    setSearchState({ query: "", category, favoritesOnly: false, testsOnly: false });
    setSearching(true);
  }

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

  useEffect(() => {
    let cancelled = false;
    listFavorites(initDataRaw)
      .then((list) => {
        if (!cancelled) {
          if (list.length > 0) {
            markFavoritesSeen();
          }
          setFavorites(list);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [initDataRaw, favoritesReloadKey]);

  function closeWorkoutView() {
    if (exitToJournal.current) {
      exitToJournal.current = false;
      onExitInitialWorkout?.();
      return;
    }
    setWorkoutView({ kind: "closed" });
    setWorkoutsReloadKey((key) => key + 1);
    setFavoritesReloadKey((key) => key + 1);
  }

  function closeProgramDetail() {
    setSelectedProgramId(null);
    setFavoritesReloadKey((key) => key + 1);
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
        onDeleted={closeWorkoutView}
        onDuplicated={closeWorkoutView}
      />
    );
  }
  if (workoutView.kind === "detail") {
    return (
      <WorkoutDetailScreen
        key={`detail-${workoutView.workoutId}`}
        initDataRaw={initDataRaw}
        workoutId={workoutView.workoutId}
        onBack={closeWorkoutView}
        onEdit={(workoutId) => setWorkoutView({ kind: "edit", workoutId })}
        onAddToPlan={(workoutId, workoutTitle) => setWorkoutView({ kind: "add-to-plan", workoutId, workoutTitle })}
        onStart={onStartWorkout}
        onLog={onLogWorkout}
      />
    );
  }
  if (workoutView.kind === "edit") {
    return (
      <WorkoutEditorScreen
        key={`edit-${workoutView.workoutId}`}
        initDataRaw={initDataRaw}
        workoutId={workoutView.workoutId}
        onBack={() => setWorkoutView({ kind: "detail", workoutId: workoutView.workoutId })}
        onSaved={() => setWorkoutView({ kind: "detail", workoutId: workoutView.workoutId })}
        onAddToPlan={(workoutId, workoutTitle) => setWorkoutView({ kind: "add-to-plan", workoutId, workoutTitle })}
        onDeleted={closeWorkoutView}
        onDuplicated={closeWorkoutView}
      />
    );
  }
  if (workoutView.kind === "add-to-plan") {
    return (
      <AddToPlanScreen
        initDataRaw={initDataRaw}
        workoutId={workoutView.workoutId}
        workoutTitle={workoutView.workoutTitle}
        onBack={() => setWorkoutView({ kind: "detail", workoutId: workoutView.workoutId })}
        onSuccess={onOpenPlans}
      />
    );
  }

  if (workoutView.kind === "add-exercise") {
    return (
      <AddToPlanScreen
        initDataRaw={initDataRaw}
        exerciseId={workoutView.exerciseId}
        workoutTitle={workoutView.exerciseName}
        onBack={() => setWorkoutView({ kind: "closed" })}
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
          initDataRaw={initDataRaw}
          program={program}
          included={included}
          adding={adding}
          addError={addState.phase === "error" ? addState.message : null}
          onAdd={() => void handleAddToPlan(program.id)}
          onBack={closeProgramDetail}
        />
      );
    }
  }

  if (collectionId !== null) {
    return (
      <CollectionScreen
        initDataRaw={initDataRaw}
        collectionId={collectionId}
        onBack={() => setCollectionId(null)}
        onOpenProgram={setSelectedProgramId}
        onOpenExercise={(exerciseId, exerciseName) => setWorkoutView({ kind: "add-exercise", exerciseId, exerciseName })}
      />
    );
  }

  if (showTests) {
    return <TestsScreen initDataRaw={initDataRaw} onBack={() => setShowTests(false)} />;
  }

  if (searching && searchTestId !== null) {
    return <TestDetailScreen initDataRaw={initDataRaw} protocolId={searchTestId} onBack={() => setSearchTestId(null)} />;
  }

  if (searching) {
    return (
      <SearchScreen
        initDataRaw={initDataRaw}
        state={searchState}
        onStateChange={setSearchState}
        onClose={() => setSearching(false)}
        onOpenProgram={setSelectedProgramId}
        onOpenWorkout={(workoutId) => setWorkoutView({ kind: "detail", workoutId })}
        onOpenTest={setSearchTestId}
        onOpenExercise={(exerciseId, exerciseName) => setWorkoutView({ kind: "add-exercise", exerciseId, exerciseName })}
      />
    );
  }

  return (
    <div>
      <div className="home-sticky-header" data-testid="home-header">
        <button type="button" className="home-search-pill" data-testid="home-search-pill" onClick={() => openSearch()}>
          Что потренируем сегодня?
        </button>
        <button
          type="button" className="home-plus-button" aria-label="Быстрые действия"
          data-testid="home-plus" onClick={() => setSheetOpen(true)}
        >
          +
        </button>
      </div>
      {sheetOpen && (
        <div className="home-sheet-backdrop" data-testid="home-sheet-backdrop" onClick={() => setSheetOpen(false)}>
          <div className="home-sheet" role="dialog" aria-label="Быстрые действия" onClick={(event) => event.stopPropagation()}>
            <button
              type="button" className="home-sheet-action"
              onClick={() => { setSheetOpen(false); setWorkoutView({ kind: "create" }); }}
            >
              Создать тренировку
            </button>
            <button
              type="button" className="home-sheet-action"
              onClick={() => { setSheetOpen(false); onOpenPlans(); }}
            >
              Тренировка на сегодня
            </button>
            <button
              type="button" className="home-sheet-action" data-testid="home-sheet-log"
              onClick={() => { setSheetOpen(false); onOpenJournalLog(); }}
            >
              Записать в журнал
            </button>
            <button type="button" className="home-sheet-action home-sheet-cancel" onClick={() => setSheetOpen(false)}>
              Отмена
            </button>
          </div>
        </div>
      )}

      <p className="plan-title">Главная</p>

      {favorites !== null && (() => {
        const mode = favoritesRowMode(favorites.length, readFavoritesSeen());
        if (mode === "hidden") {
          return null;
        }
        return (
          <div data-testid="favorites-row">
            <p className="section-title">Избранное</p>
            {mode === "hint" ? (
              <p className="screen-message" data-testid="favorites-hint">Нажмите ♡ на тренировке, чтобы добавить</p>
            ) : (
              <div className="home-program-row">
                {favorites.map((favorite) => (
                  <Section key={`${favorite.target_type}-${favorite.target_id}`} className="block-section home-program-card">
                    <button
                      type="button"
                      className="program-card-button"
                      data-testid="favorite-card"
                      onClick={() => (favorite.target_type === "workout"
                        ? setWorkoutView({ kind: "detail", workoutId: favorite.target_id })
                        : setSelectedProgramId(favorite.target_id))}
                    >
                      <p className="block-subtitle">{favorite.title}</p>
                      {favorite.subtitle && <p className="screen-message">{favorite.subtitle}</p>}
                    </button>
                  </Section>
                ))}
              </div>
            )}
          </div>
        );
      })()}

      <CollectionsRow initDataRaw={initDataRaw} onOpen={setCollectionId} />

      <button type="button" className="home-tests-row" data-testid="home-tests-row" onClick={() => setShowTests(true)}>
        <span className="home-tests-row-title">Тесты</span>
        <span className="hint">Максимум, вис, вес — результаты и динамика ›</span>
      </button>

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
      {catalog.phase === "ready" && groupProgramsByCategory(catalog.programs).map((row) => (
        <div key={row.category} data-testid="program-category">
          <div className="home-section-header">
            <p className="section-title" data-testid="program-category-title">{row.category}</p>
            {row.category !== OTHER_CATEGORY && (
              <Button size="s" mode="plain" data-testid="program-category-all" onClick={() => openSearch(row.category)}>
                Все ›
              </Button>
            )}
          </div>
          <div className="home-program-row" data-testid="program-row">
            {row.programs.map((program) => {
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
        </div>
      ))}

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
                  onClick={() => setWorkoutView({ kind: "detail", workoutId: workout.id })}
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
