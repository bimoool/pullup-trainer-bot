import type {
  AssessmentProtocolV2, FavoriteV2, ExerciseResponseV2, ProgramResponseV2, WorkoutResponseV2,
} from "./apiV2";

/** Название ряда для программ без категории. */
export const OTHER_CATEGORY = "Другое";

export type ProgramRow = { category: string; programs: ProgramResponseV2[] };

function normalizedCategory(category: string | null | undefined): string {
  const value = (category ?? "").trim();
  return value === "" ? OTHER_CATEGORY : value;
}

/** Программы по рядам-категориям: порядок рядов — по первому появлению,
 * «Другое» (без категории) всегда последним. */
export function groupProgramsByCategory(programs: ProgramResponseV2[]): ProgramRow[] {
  const rows = new Map<string, ProgramResponseV2[]>();
  for (const program of programs) {
    const key = normalizedCategory(program.category);
    const list = rows.get(key);
    if (list) {
      list.push(program);
    } else {
      rows.set(key, [program]);
    }
  }
  const result = [...rows.entries()].map(([category, list]) => ({ category, programs: list }));
  return [
    ...result.filter((row) => row.category !== OTHER_CATEGORY),
    ...result.filter((row) => row.category === OTHER_CATEGORY),
  ];
}

/** Цвет программы = цвет её группы-ряда на Главной (`--vp-cat-{rowIndex % 6}`, #280); null — программа не найдена. */
export function programCategoryColorVar(programs: ProgramResponseV2[], programId: number): string | null {
  const rows = groupProgramsByCategory(programs);
  const index = rows.findIndex((row) => row.programs.some((program) => program.id === programId));
  return index < 0 ? null : `var(--vp-cat-${index % 6})`;
}

/** Категории, реально присутствующие в загруженных программах и упражнениях. */
export function collectCategories(
  programs: ProgramResponseV2[], exercises: ExerciseResponseV2[],
): string[] {
  const seen = new Set<string>();
  for (const item of [...programs, ...exercises]) {
    const raw = (item.category ?? "").trim();
    if (raw !== "") {
      seen.add(raw);
    }
  }
  return [...seen].sort((a, b) => a.localeCompare(b, "ru"));
}

function matches(text: string, query: string): boolean {
  return text.toLocaleLowerCase("ru").includes(query);
}

export type SearchResults = {
  programs: ProgramResponseV2[];
  workouts: WorkoutResponseV2[];
  exercises: ExerciseResponseV2[];
  /** Тесты (Assessment Tests, #281 D6): отдельная группа результатов поиска. */
  tests: AssessmentProtocolV2[];
  total: number;
};

/** Клиентский поиск по подстроке (без учёта регистра) + фильтр категории.
 * У тренировок категории нет — при активном фильтре категории они скрыты.
 * `favorites` != null — чип «Избранное»: только избранные программы и тренировки
 * (упражнения в избранное не добавляются). Тесты (#281): у них нет категории и они не
 * добавляются в избранное — скрыты при фильтре категории/избранного; `testsOnly` — чип
 * «Тесты»: только тесты. */
export function searchContent(
  data: {
    programs: ProgramResponseV2[]; workouts: WorkoutResponseV2[]; exercises: ExerciseResponseV2[];
    assessments?: AssessmentProtocolV2[];
  },
  rawQuery: string,
  category: string | null,
  favorites: FavoriteV2[] | null = null,
  testsOnly = false,
): SearchResults {
  const inFavorites = (type: FavoriteV2["target_type"], id: number) =>
    favorites === null || favorites.some((f) => f.target_type === type && f.target_id === id);
  const query = rawQuery.trim().toLocaleLowerCase("ru");
  const programs = testsOnly ? [] : data.programs.filter(
    (p) => inFavorites("program", p.id)
      && (category === null || (p.category ?? "").trim() === category)
      && (query === "" || matches(p.name, query) || matches(p.goal ?? "", query)),
  );
  const workouts = category !== null || testsOnly
    ? []
    : data.workouts.filter((w) => inFavorites("workout", w.id) && (query === "" || matches(w.title, query)));
  const exercises = testsOnly ? [] : data.exercises.filter(
    (e) => favorites === null && (category === null || (e.category ?? "").trim() === category)
      && (query === "" || matches(e.name, query)),
  );
  const tests = category !== null || favorites !== null
    ? []
    : (data.assessments ?? []).filter((t) => query === "" || matches(t.name, query) || matches(t.description ?? "", query));
  return {
    programs, workouts, exercises, tests,
    total: programs.length + workouts.length + exercises.length + tests.length,
  };
}

export type SearchFilters = { category: string | null; favoritesOnly: boolean; testsOnly: boolean };

/** Нажатие на чип фильтра поиска (#284 C3). «Тесты» несовместимы с «Избранным» и категориями
 * (у тестов нет категории и избранного — комбинация всегда давала «Ничего не найдено»):
 * включение «Тестов» сбрасывает остальные чипы, включение любого другого — «Тесты».
 * «Избранное» и категория между собой комбинируются. Повторное нажатие снимает чип. */
export function toggleSearchFilter<T extends SearchFilters>(
  state: T,
  chip: { kind: "tests" } | { kind: "favorites" } | { kind: "category"; category: string },
): T {
  if (chip.kind === "tests") {
    return state.testsOnly
      ? { ...state, testsOnly: false }
      : { ...state, testsOnly: true, favoritesOnly: false, category: null };
  }
  if (chip.kind === "favorites") {
    return { ...state, favoritesOnly: !state.favoritesOnly, testsOnly: false };
  }
  return { ...state, category: chip.category === state.category ? null : chip.category, testsOnly: false };
}
