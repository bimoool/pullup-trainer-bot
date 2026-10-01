import type { ExerciseResponseV2, ProgramResponseV2, WorkoutResponseV2 } from "./apiV2";

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
  total: number;
};

/** Клиентский поиск по подстроке (без учёта регистра) + фильтр категории.
 * У тренировок категории нет — при активном фильтре категории они скрыты. */
export function searchContent(
  data: { programs: ProgramResponseV2[]; workouts: WorkoutResponseV2[]; exercises: ExerciseResponseV2[] },
  rawQuery: string,
  category: string | null,
): SearchResults {
  const query = rawQuery.trim().toLocaleLowerCase("ru");
  const programs = data.programs.filter(
    (p) => (category === null || (p.category ?? "").trim() === category)
      && (query === "" || matches(p.name, query) || matches(p.goal ?? "", query)),
  );
  const workouts = category !== null
    ? []
    : data.workouts.filter((w) => query === "" || matches(w.title, query));
  const exercises = data.exercises.filter(
    (e) => (category === null || (e.category ?? "").trim() === category)
      && (query === "" || matches(e.name, query)),
  );
  return { programs, workouts, exercises, total: programs.length + workouts.length + exercises.length };
}
