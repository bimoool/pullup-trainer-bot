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
