import type {
  AssessmentProtocolV2, FavoriteV2, ExerciseResponseV2, ProgramResponseV2, WorkoutResponseV2,
} from "./apiV2";

/** Название ряда для программ без категории. */
export const OTHER_CATEGORY = "Другое";

/** Ключ категории без значения: у программы нет категории (ряд «Другое»). */
export const OTHER_KEY = "";

/** `category` — ВНУТРЕННИЙ ключ (группировка, фильтр поиска, действие «Все ›», цвет); `label` — подпись для
 * показа. Ключ и подпись различаются сознательно: технический слаг не показываем, но и не склеиваем разные ключи. */
export type ProgramRow = { category: string; label: string; programs: ProgramResponseV2[] };

/** Подписи слагов СИДОВЫХ категорий каталога (app/domain/exercise_identity.py::CATEGORY_SEEDS): у программ
 * `category` — слаг («pull_ups»), у упражнений — уже подпись («Подтягивания»). */
const CATEGORY_LABELS: Record<string, string> = {
  pull_ups: "Подтягивания",
  grip: "Хват",
  general_fitness: "Общая физическая подготовка",
  my_exercises: "Мои упражнения",
  uncategorized: "Без категории",
};
const LABEL_TO_KEY: Record<string, string> = Object.fromEntries(
  Object.entries(CATEGORY_LABELS).map(([key, label]) => [label.toLowerCase(), key]),
);

/** Внутренний ключ категории. Только ИЗВЕСТНЫЕ сидовые слаг/подпись сводятся к одному ключу (это одна категория
 * в двух представлениях: слаг программы и подпись упражнения); любые другие значения — как есть (по обрезанным
 * пробелам, с учётом регистра): разные категории никогда не сливаются. Пусто — `OTHER_KEY`. */
export function categoryKey(category: string | null | undefined): string {
  const value = (category ?? "").trim();
  if (value === "") {
    return OTHER_KEY;
  }
  const lower = value.toLowerCase();
  if (lower in CATEGORY_LABELS) {
    return lower;
  }
  return LABEL_TO_KEY[lower] ?? value;
}

/** Подпись категории для показа (по ключу или сырому значению): сидовый слаг — по справочнику, прочий
 * технический слаг (`snake_case`) — слова через пробел с заглавной (только показ, ключ не меняется). */
export function categoryLabel(category: string | null | undefined): string {
  const key = categoryKey(category);
  if (key === OTHER_KEY) {
    return OTHER_CATEGORY;
  }
  const known = CATEGORY_LABELS[key];
  if (known !== undefined) {
    return known;
  }
  if (/^[A-Za-z0-9]+(_[A-Za-z0-9]+)+$/.test(key)) {
    const words = key.toLowerCase().split("_").join(" ");
    return words.charAt(0).toUpperCase() + words.slice(1);
  }
  return key;
}

/** Программы по рядам-категориям (по КЛЮЧУ): порядок рядов — по первому появлению, «Другое» последним. */
export function groupProgramsByCategory(programs: ProgramResponseV2[]): ProgramRow[] {
  const rows = new Map<string, ProgramResponseV2[]>();
  for (const program of programs) {
    const key = categoryKey(program.category);
    const list = rows.get(key);
    if (list) {
      list.push(program);
    } else {
      rows.set(key, [program]);
    }
  }
  const result = [...rows.entries()].map(([category, list]) => ({
    category, label: categoryLabel(category), programs: list,
  }));
  return [
    ...result.filter((row) => row.category !== OTHER_KEY),
    ...result.filter((row) => row.category === OTHER_KEY),
  ];
}

/** Число цветов категориальной палитры `--vp-cat-0..5` (shell.css). */
export const CATEGORY_PALETTE_SIZE = 6;

/** Порядок категорий на Главной (КЛЮЧИ): ряды групп (`groupProgramsByCategory`), «Другое» последним. */
export function homeCategoryOrder(programs: ProgramResponseV2[]): string[] {
  return groupProgramsByCategory(programs).map((row) => row.category);
}

/** Стабильный индекс палитры по имени (djb2) — для категорий, которых нет в рядах Главной. */
function hashIndex(name: string): number {
  let hash = 5381;
  for (let i = 0; i < name.length; i += 1) {
    hash = (hash * 33 + name.charCodeAt(i)) >>> 0;
  }
  return hash % CATEGORY_PALETTE_SIZE;
}

/** Цвет категории — функция ИМЕНИ (#286): та же категория красится одинаково на Главной, в Планах
 * и в Аналитике, независимо от порядка сортировки. Категория из рядов Главной получает
 * `--vp-cat-{индекс ряда % 6}`; остальные — стабильный хеш имени. */
export function categoryColorVar(name: string, homeOrder: string[]): string {
  const key = categoryKey(name);
  const index = homeOrder.indexOf(key);
  return `var(--vp-cat-${index >= 0 ? index % CATEGORY_PALETTE_SIZE : hashIndex(key)})`;
}

/** «Чернила» цвета категории для ТЕКСТА (чип/подпись, #288): `var(--vp-cat-3)` → `var(--vp-cat-3-ink)`. */
export function categoryInkVar(colorVar: string): string {
  return colorVar.replace(/\)$/, "-ink)");
}

/** Цвет программы = цвет её категории (см. `categoryColorVar`); null — программа не найдена. */
export function programCategoryColorVar(programs: ProgramResponseV2[], programId: number): string | null {
  const program = programs.find((item) => item.id === programId);
  return program === undefined ? null : categoryColorVar(categoryKey(program.category), homeCategoryOrder(programs));
}

/** КЛЮЧИ категорий, реально присутствующих в загруженных программах и упражнениях (по подписи, ru). */
export function collectCategories(
  programs: ProgramResponseV2[], exercises: ExerciseResponseV2[],
): string[] {
  const seen = new Set<string>();
  for (const item of [...programs, ...exercises]) {
    const key = categoryKey(item.category);
    if (key !== OTHER_KEY) {
      seen.add(key);
    }
  }
  return [...seen].sort((a, b) => categoryLabel(a).localeCompare(categoryLabel(b), "ru") || a.localeCompare(b));
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
      && (category === null || categoryKey(p.category) === category)
      && (query === "" || matches(p.name, query) || matches(p.goal ?? "", query)),
  );
  const workouts = category !== null || testsOnly
    ? []
    : data.workouts.filter((w) => inFavorites("workout", w.id) && (query === "" || matches(w.title, query)));
  const exercises = testsOnly ? [] : data.exercises.filter(
    (e) => favorites === null && (category === null || categoryKey(e.category) === category)
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
