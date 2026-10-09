import { Button, Section } from "@telegram-apps/telegram-ui";
import { Icon } from "./Icon";
import { useEffect, useRef, useState } from "react";

import { fetchDashboard, type DashboardResponse } from "./api";
import {
  copyPlanWeekToNext,
  createPlanItem,
  createPlanWeek,
  type ExerciseResponseV2,
  fetchExercises,
  fetchPlan,
  fetchPrograms,
  type PlanItemResponseV2,
  type PlanWeekResponseV2,
  type ProgramResponseV2,
  type ProgramInclusionResponseV2,
  type CustomPlanV2,
  removePlanItem,
  deactivateCustomPlan,
  deactivateProgramInclusion,
  type TrainingPlanResponseV2,
} from "./apiV2";
import { categoryInkVar, programCategoryColorVar } from "./homeDiscovery";
import { completedInclusions, inclusionDateRange, inclusionWeekLabel } from "./plansOverview";
import { STATUS_MESSAGES } from "./WorkoutScreen";
import { ActionSheet, MoreButton, PlanProgressBar, type SheetAction } from "./ActionSheet";
import { AddToPlanScreen } from "./AddToPlanScreen";
import { CustomPlanScreen } from "./CustomPlanScreen";
import { MovePlanItemScreen } from "./MovePlanItemScreen";
import { MyWorkoutsScreen } from "./MyWorkoutsScreen";
import { WorkoutDetailScreen } from "./WorkoutDetailScreen";
import { WorkoutEditorScreen } from "./WorkoutEditorScreen";
import {
  canAdvanceWeek, groupCounter, isEditableWeek, localToday, progressPercent, resolveCurrentWeekIndex, stepWeek,
  occurrenceStateLabel, todayDayIndexInWeek, weekProgress, weekRangeLabel,
} from "./planWeekNav";

// issue #193 (WORKER B) — соглашение 0=понедельник..6=воскресенье
// (Python date.weekday()), тот же порядок, что и остальной код проекта
// использует для дат: ни одна существующая строка PlanItem.day_of_week
// сейчас не NULL (см. scripts/backfill_multi_program.py — реальный сид
// "Подтягивания" целиком свободный пул), так что до этого issue нумерация
// нигде не была задокументирована и не использовалась — выбрана здесь
// первый раз.
const DAY_NAMES = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"];

const WEEK_PHASE_LABELS: Record<string, string> = {
  base: "База", rest: "Отдых", peak: "Пик",
};

/** Имя строки плана для отображения. Checkpoint 3 (issue #188, Worker C
 * blocking fix) — раньше искало только в snapshot.exercises инклюзии,
 * поэтому manual PlanItem (program_inclusion_id=NULL — «Планка»/
 * «Отжимания», добавленные через picker ниже) всегда падали в фолбэк
 * "Упражнение #id". Порядок разрешения: (1) snapshot той инклюзии, что
 * произвела строку — для program-backed PlanItem; (2) Exercise Library
 * (GET /exercises, загружена этим же экраном для picker'а) — для manual;
 * (3) `Упражнение #id`/`Комплекс` — только если оба источника не знают
 * это имя (реально недостижимо для реально созданных через этот экран
 * строк, честный фолбэк на случай рассинхрона данных). Backend-схема не
 * менялась — по прямому указанию, имя не хранится на самом PlanItem. */
function exerciseLabel(
  item: PlanItemResponseV2, inclusions: ProgramInclusionResponseV2[], exercises: ExerciseResponseV2[],
): string {
  // Phase B2 gate fix (issue #215) — Workout title (Complex.name) имеет
  // приоритет над резолвом через exercise_id для complex-based PlanItem:
  // exercise_id на таком PlanItem может быть посторонним/decoy значением
  // (интервальные Workout не хранят "какое упражнение" через exercise_id
  // вообще — это делает ComplexItem внутри Workout), реальное имя
  // тренировки только в Complex.name.
  if (item.complex_id !== null && item.complex_name !== null) {
    return item.complex_name;
  }
  for (const inclusion of inclusions) {
    const match = inclusion.snapshot.exercises?.find((exercise) => exercise.exercise_id === item.exercise_id);
    if (match) {
      return match.name;
    }
  }
  const libraryMatch = exercises.find((exercise) => exercise.id === item.exercise_id);
  if (libraryMatch) {
    return libraryMatch.name;
  }
  return item.complex_id !== null ? "Комплекс" : `Упражнение #${item.exercise_id}`;
}

type PlanItemGroup = { key: string; title: string; items: PlanItemResponseV2[] };

/** Группировка строк плана в пользовательские карточки тренировки —
 * integration fix (issue #188, checkpoint 2 review): без этого «Подтягивания»
 * (2 PlanItem — Блок A/Блок Б, одна ProgramInclusion) показывались двумя
 * отдельными строками вместо одной карточки "Подтягивания".
 *
 * Ключ группы — (program_inclusion_id, day_of_week), day_of_week=NULL
 * (свободный пул) — валидный самостоятельный бакет, не особый случай.
 * Тот же группирующий ключ уже использует SessionPreScreen.tsx::
 * planItemIdsForInclusion для старта живой сессии — не новая семантика,
 * подтверждено read-only review (issue #194).
 *
 * Заголовок карточки — ProgramInclusionResponse.program_name, не имя
 * отдельного упражнения (issue #192/#193 путали это).
 *
 * Ручные строки (program_inclusion_id=NULL) НЕ объединяются друг с другом
 * автоматически, даже при совпадении дня — каждая своя отдельная карточка
 * (докстринг PlanItem, app/db/models_program.py: "строки от разных
 * источников не объединяются автоматически"). */
function groupPlanItems(
  items: PlanItemResponseV2[], inclusions: ProgramInclusionResponseV2[], exercises: ExerciseResponseV2[],
): PlanItemGroup[] {
  const groups = new Map<string, PlanItemGroup>();
  let manualSeq = 0;
  for (const item of items) {
    // issue #304 (AD-4): занятие курса — своя карточка (одна строка = одно занятие, «0 из 3»).
    if (item.program_inclusion_id !== null && item.occurrence_index !== null && item.occurrence_index !== undefined) {
      const key = `occ:${item.id}`;
      const inclusion = inclusions.find((i) => i.id === item.program_inclusion_id);
      groups.set(key, { key, title: inclusion?.program_name ?? exerciseLabel(item, inclusions, exercises), items: [item] });
      continue;
    }
    if (item.program_inclusion_id === null) {
      const key = `manual:${item.id}:${manualSeq++}`;
      groups.set(key, { key, title: exerciseLabel(item, inclusions, exercises), items: [item] });
      continue;
    }
    const key = `${item.program_inclusion_id}:${item.day_of_week ?? "null"}`;
    const existing = groups.get(key);
    if (existing) {
      existing.items.push(item);
    } else {
      const inclusion = inclusions.find((i) => i.id === item.program_inclusion_id);
      groups.set(
        key,
        { key, title: inclusion?.program_name ?? exerciseLabel(item, inclusions, exercises), items: [item] },
      );
    }
  }
  return [...groups.values()];
}

type Props = {
  initDataRaw: string;
  /** Checkpoint 4A/4B (issue #188) — "Начать" на карточке любой группы
   * (program-backed "Подтягивания" ИЛИ manual "Планка"/"Отжимания") ведёт
   * сюда с точным набором plan_item_id этой группы (тот же ключ, что
   * groupPlanItems уже использует для отображения — не пересчитывается
   * заново). manual=true — program_inclusion_id этой группы NULL, у
   * SessionPreScreen нет ProgramInclusion, по которому читать readiness
   * (не тот же вопрос, что STEP-readiness "Подтягиваний"). title — то же
   * group.title, что уже показывает карточка, не пересчитывается заново
   * через Exercise Library на следующем экране. */
  onStartSession: (planItemIds: number[], options: { manual: boolean; title: string }) => void;
  /** Workout Detail «Начать» / «Записать» (свободная сессия и запись задним числом). */
  onStartWorkout: (workoutId: number, workoutTitle: string) => void;
  onLogWorkout: (workoutId: number) => void;
  /** Вернулись из «Записать» (#277): открыть сразу Workout Detail этой тренировки. */
  initialWorkoutId?: number | null;
  onInitialWorkoutShown?: () => void;
  /** «Выбрать курс» в пустом плане (#277, D3) — на Главную, где каталог программ. */
  onOpenHome?: () => void;
};

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; dashboard: DashboardResponse };

/** Та же нижняя граница, что у app.domain.achievements.consecutive_streak_length:
 * 1 — единственная тренировка, это ещё не "серия" в разговорном смысле,
 * поэтому стрик показывается как число только от 2.
 *
 * Экспортирована (issue #183, волна 5b) — тот же расчёт нужен компактному
 * виджету недели на "Главной" (HomeScreen.tsx), не только полной карточке
 * здесь на "Планах". */
export function streakValue(streak: number, workoutsCount: number): string {
  if (workoutsCount === 0 || streak <= 1) {
    return "—";
  }
  return String(streak);
}

/** Серия с SVG-пламенем вместо эмодзи (#290): число из streakValue, «—» без значка. */
export function StreakValue({ streak, workoutsCount }: { streak: number; workoutsCount: number }) {
  const value = streakValue(streak, workoutsCount);
  if (value === "—") {
    return <>{value}</>;
  }
  return (
    <span className="streak-value">
      <Icon name="flame" size={16} /> {value}
    </span>
  );
}

type PlanState = {
  inclusions: ProgramInclusionResponseV2[];
  items: PlanItemResponseV2[];
  weeks: PlanWeekResponseV2[];
  /** current_week_id с сервера (часовой пояс пользователя). */
  currentWeekId: number | null;
  /** plan.today с сервера (YYYY-MM-DD, часовой пояс пользователя); null — старый ответ, тогда localToday(). */
  today: string | null;
  /** issue #304 — свои планы с объёмом по неделям. */
  customPlans: CustomPlanV2[];
};

const EMPTY_PLAN: PlanState = { inclusions: [], items: [], weeks: [], currentWeekId: null, today: null, customPlans: [] };

/** #288 — план старше этого (мс) перечитывается при возврате в приложение: «Сегодня» не залипает на вчера. */
const PLAN_STALE_MS = 60_000;

/** issue #266 — inclusions содержит и неактивные (вкладка «Завершённые»);
 * строки убранных курсов в недельный вид не попадают (история в БД остаётся). */
function toPlanState(data: TrainingPlanResponseV2 | null): PlanState {
  if (data === null) {
    return EMPTY_PLAN;
  }
  const inactiveIds = new Set(data.program_inclusions.filter((i) => !i.is_active).map((i) => i.id));
  return {
    inclusions: data.program_inclusions,
    items: data.plan_items.filter(
      (item) => item.program_inclusion_id === null || !inactiveIds.has(item.program_inclusion_id),
    ),
    weeks: data.plan_weeks,
    currentWeekId: data.current_week_id ?? null,
    today: data.today ?? null,
    customPlans: data.custom_plans ?? [],
  };
}

// Phase C4a/C5a/D3 (issue #188) — «Мои тренировки» + Plans card actions
// swap-state.
type MyWorkoutsView =
  | { kind: "closed" }
  | { kind: "custom-plan" }
  | { kind: "list" }
  | { kind: "create" }
  | { kind: "detail"; workoutId: number }
  | { kind: "edit"; workoutId: number; openPicker?: boolean }
  | { kind: "add-to-plan"; workoutId: number; workoutTitle: string; returnTo: "list" | "edit" | "detail" }
  | { kind: "move-plan-item"; planItemId: number; title: string; currentDayOfWeek: number | null; planWeekId: number | null };

/** #286 B — какой лист «⋯» открыт на экране «Планы». */
type PlansSheetState =
  | {
    kind: "row"; planItemId: number; title: string; dayOfWeek: number | null; planWeekId: number | null;
    /** id пользовательской тренировки — только для «Редактировать тренировку». */
    editWorkoutId: number | null;
    /** issue #304 — занятие курса: только перенос (убрать — через «Убрать курс»). */
    moveOnly?: boolean;
  }
  | { kind: "plan"; inclusionId: number | null };

type ExercisesState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; exercises: ExerciseResponseV2[] };

// Checkpoint 3 (issue #188) — picker "+ Добавить упражнение" внутри текущей
// PlanWeek. day: null означает "Свободный пул" — валидный выбор, не
// "не выбрано". exerciseId: null означает "не выбрано" — кнопка "Добавить"
// неактивна до выбора.
type PickerState =
  | { phase: "closed" }
  | { phase: "picking"; weekId: number; exerciseId: number | null; day: number | null }
  | { phase: "adding"; weekId: number; exerciseId: number; day: number | null }
  | { phase: "add-error"; weekId: number; exerciseId: number; day: number | null; message: string };

/** Только честные статусы (issue #175, docs/architecture-multicourse.md:
 * "нельзя предлагать действие, которое гарантированно не может завершиться
 * успехом") — кнопка ниже обещает "начать тренировку" ТОЛЬКО на status=
 * "ready". На любом другом статусе она просто открывает раздел "Тренировка",
 * где WorkoutScreen (тот же STATUS_MESSAGES) объясняет причину и предлагает
 * то, что реально доступно (факультатив/бэкдейт/бот) — Dashboard не
 * дублирует эту логику, только не начинает с неё. */
export function DashboardScreen({ initDataRaw, onStartSession, onStartWorkout, onLogWorkout, initialWorkoutId = null, onInitialWorkoutShown, onOpenHome }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
  // Подключённые курсы + реальные PlanWeek (Capability A issue #188, недели
  // — issue #193) — минимальный видимый результат "Добавить в план" (10.2:
  // "полоса недель ... внизу Подключённые курсы"). Отдельный эффект и
  // молчаливый провал (пустое состояние), чтобы не рвать уже рабочую сводку
  // "Сегодня", если /api/v2/plan недоступен по какой-то причине.
  const [plan, setPlan] = useState<PlanState>(EMPTY_PLAN);
  // Exercise Library (issue #196) — загружается один раз при открытии
  // "Планов", тем же способом, что и dashboard/plan выше: отдельный эффект,
  // молчаливый провал не рвёт остальной экран, если /api/v2/exercises
  // недоступен по какой-то причине — просто не будет "+ Добавить упражнение".
  const [exercisesState, setExercisesState] = useState<ExercisesState>({ phase: "loading" });
  const [picker, setPicker] = useState<PickerState>({ phase: "closed" });
  // Каталог нужен только чтобы подкрасить карточки курсов цветом категории (как группы Главной, #280);
  // сбой молча — карточки остаются нейтральными.
  const [catalogPrograms, setCatalogPrograms] = useState<ProgramResponseV2[]>([]);
  // Для пустого «Планы» (#298): есть ли вообще что выбирать. loading — не обещаем ничего, пока не знаем.
  const [catalogStatus, setCatalogStatus] = useState<"loading" | "ready" | "error">("loading");
  // H1, microfix 2 (issue #188) — UI-guard против двойного тапа "Начать":
  // onStartSession синхронно переключает App.tsx на PlanSessionFlow
  // (никакого сетевого запроса на этом уровне, сам запрос — уже внутри
  // SessionPreScreen после навигации), поэтому окно гонки — доля секунды
  // между кликом и следующим рендером React, но два очень быстрых тапа
  // успевают попасть в него оба. Backend остаётся последней защитой
  // (client_session_id-идемпотентность, Checkpoint 4A) — это только UX,
  // не замена ей. Сброс "при ошибке" не нужен отдельно: onStartSession
  // здесь не может провалиться сам по себе (это не API-вызов), при успехе
  // компонент размонтируется вместе с переходом на PlanSessionFlow.
  const [startingGroupKey, setStartingGroupKey] = useState<string | null>(null);
  // Phase C4a (issue #188) — «Мои тренировки», локальный swap-state внутри
  // Планов, тот же принцип, что HomeScreen.tsx уже использует для
  // ProgramDetailScreen (selectedProgramId), не отдельный App.tsx Tab.
  const [myWorkoutsView, setMyWorkoutsView] = useState<MyWorkoutsView>(
    initialWorkoutId !== null ? { kind: "detail", workoutId: initialWorkoutId } : { kind: "closed" },
  );
  useEffect(() => {
    if (initialWorkoutId !== null) {
      onInitialWorkoutShown?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- только при монтировании.
  }, []);
  // Phase D3 (issue #188) — inline "Убрать из плана?" confirm на карточке,
  // тот же паттерн, что WorkoutEditorScreen.tsx уже использует для
  // удаления item'а (deleteConfirmItemId).
  const [removeConfirmPlanItemId, setRemoveConfirmPlanItemId] = useState<number | null>(null);
  const [removingPlanItemId, setRemovingPlanItemId] = useState<number | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);
  // issue #258 — выбранная неделя (id PlanWeek); null = текущая.
  const [selectedWeekId, setSelectedWeekId] = useState<number | null>(null);
  // issue #266 — «Сейчас | Завершённые» и «Убрать курс из плана» (inline-подтверждение).
  const [overviewTab, setOverviewTab] = useState<"now" | "completed">("now");
  const [removeInclusionConfirmId, setRemoveInclusionConfirmId] = useState<number | null>(null);
  const [removingInclusionId, setRemovingInclusionId] = useState<number | null>(null);
  const [stoppingCustomPlanId, setStoppingCustomPlanId] = useState<number | null>(null);
  const [customPlanError, setCustomPlanError] = useState<string | null>(null);
  const [inclusionError, setInclusionError] = useState<string | null>(null);

  // issue #275 — планирование вперёд: › за последней неделей создаёт следующую;
  // «Скопировать неделю» — с подтверждением.
  const [weekBusy, setWeekBusy] = useState(false);
  const [weekError, setWeekError] = useState<string | null>(null);
  const [copyConfirm, setCopyConfirm] = useState(false);
  const [copyResult, setCopyResult] = useState<string | null>(null);
  // #286 B — нижние листы «⋯»: действия строки дня и плана (курса). Смонтирован = открыт.
  const [sheet, setSheet] = useState<PlansSheetState | null>(null);
  // #288 — «⋯», с которой открыли лист (туда вернётся фокус; на iOS тап не фокусирует кнопку),
  // и ключ «⋯», которой нужно вернуть фокус после подтверждения/«Отмены» (пока подтверждение — «⋯» скрыта).
  const [sheetOpener, setSheetOpener] = useState<HTMLElement | null>(null);
  const [pendingFocusKey, setPendingFocusKey] = useState<string | null>(null);
  const copyConfirmRef = useRef<HTMLDivElement>(null);
  function openSheet(next: PlansSheetState, opener: HTMLElement) {
    setSheetOpener(opener);
    setSheet(next);
  }

  async function handleAdvanceWeek(lastWeek: PlanWeekResponseV2) {
    setWeekBusy(true);
    setWeekError(null);
    try {
      const created = await createPlanWeek(initDataRaw, lastWeek.week_number + 1);
      await reloadPlan();
      setSelectedWeekId(created.id);
    } catch (error) {
      setWeekError(error instanceof Error ? error.message : String(error));
    } finally {
      setWeekBusy(false);
    }
  }

  async function handleCopyWeek(weekId: number) {
    setWeekBusy(true);
    setWeekError(null);
    setCopyResult(null);
    try {
      const result = await copyPlanWeekToNext(initDataRaw, weekId);
      setCopyConfirm(false);
      await reloadPlan();
      setSelectedWeekId(result.target_week.id);
      setCopyResult(`Скопировано: ${result.copied}, пропущено дублей: ${result.skipped}`);
    } catch (error) {
      setWeekError(error instanceof Error ? error.message : String(error));
    } finally {
      setWeekBusy(false);
    }
  }

  // #288 — когда и при какой локальной дате план загружен: по этому решаем, не устарело ли «Сегодня».
  const planLoadedRef = useRef({ at: Date.now(), localDate: localToday() });

  function applyPlan(data: TrainingPlanResponseV2 | null) {
    planLoadedRef.current = { at: Date.now(), localDate: localToday() };
    setPlan(toPlanState(data));
  }

  function reloadPlan() {
    return fetchPlan(initDataRaw).then(applyPlan);
  }

  // Phase D3 (issue #188) — «Убрать из плана». Confirm/Cancel — inline на
  // карточке, тот же паттерн, что WorkoutEditorScreen.tsx уже использует.
  async function handleRemovePlanItem(planItemId: number) {
    setRemovingPlanItemId(planItemId);
    setRemoveError(null);
    try {
      await removePlanItem(initDataRaw, planItemId);
      setRemoveConfirmPlanItemId(null);
      await reloadPlan();
    } catch (error) {
      setRemoveError(error instanceof Error ? error.message : String(error));
    } finally {
      setRemovingPlanItemId(null);
    }
  }

  async function handleRemoveInclusion(inclusionId: number) {
    setRemovingInclusionId(inclusionId);
    setInclusionError(null);
    try {
      await deactivateProgramInclusion(initDataRaw, inclusionId);
      setRemoveInclusionConfirmId(null);
      await reloadPlan();
    } catch (error) {
      setInclusionError(error instanceof Error ? error.message : String(error));
    } finally {
      setRemovingInclusionId(null);
    }
  }

  // issue #304 (B3) — «Остановить план»: свой план больше не добавляет занятия, история остаётся.
  async function handleStopCustomPlan(customPlanId: number, name: string) {
    if (!window.confirm(`Остановить план «${name}»? Выполненные тренировки останутся в истории.`)) {
      return;
    }
    setStoppingCustomPlanId(customPlanId);
    setCustomPlanError(null);
    try {
      await deactivateCustomPlan(initDataRaw, customPlanId);
      await reloadPlan();
    } catch (error) {
      setCustomPlanError(error instanceof Error ? error.message : String(error));
    } finally {
      setStoppingCustomPlanId(null);
    }
  }

  function handleAddExercise(weekId: number) {
    setPicker({ phase: "picking", weekId, exerciseId: null, day: null });
  }

  function updatePickerSelection(patch: { exerciseId?: number; day?: number | null }) {
    if (picker.phase !== "picking" && picker.phase !== "add-error") {
      return;
    }
    setPicker({
      phase: "picking", weekId: picker.weekId,
      exerciseId: patch.exerciseId ?? picker.exerciseId,
      day: patch.day !== undefined ? patch.day : picker.day,
    });
  }

  function handleConfirmAdd() {
    // Guard against duplicate in-flight requests (issue #211, HA-3: double-tap
    // protection after user changes selection in "add-error" → "picking"
    // transition). Slightly redundant with second check, but explicit intent.
    if (picker.phase === "adding") {
      return;
    }
    if (picker.phase !== "picking" || picker.exerciseId === null) {
      return;
    }
    const { weekId, exerciseId, day } = picker;
    setPicker({ phase: "adding", weekId, exerciseId, day });
    createPlanItem(initDataRaw, {
      exercise_id: exerciseId, plan_week_id: weekId, day_of_week: day, count_per_week: 1,
    })
      .then(() => reloadPlan())
      .then(() => {
        // Checkpoint 3 (issue #188, раздел 5): не добавлять строку локально
        // — refetch реального GET /plan, UI строится из серверного
        // состояния, не из оптимистичного предположения.
        setPicker({ phase: "closed" });
      })
      .catch((error) => {
        setPicker({
          phase: "add-error", weekId, exerciseId, day,
          message: error instanceof Error ? error.message : String(error),
        });
      });
  }

  useEffect(() => {
    let cancelled = false;
    fetchPlan(initDataRaw)
      .then((data) => {
        if (!cancelled) {
          applyPlan(data);
        }
      })
      .catch(() => {
        // молчаливо — см. комментарий у объявления state выше
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- applyPlan стабилен по смыслу (только setPlan и ref).
  }, [initDataRaw]);

  // #288 — приложение может быть открыто всю ночь или вернуться из фона на следующий день: «Сегодня»
  // считается от plan.today (дата пользователя на сервере), поэтому при смене даты или устаревшем плане
  // перечитываем план (тихо). Дата устройства может отличаться от даты пользователя, поэтому ещё и по возрасту.
  useEffect(() => {
    let cancelled = false;
    let midnightTimer: ReturnType<typeof setTimeout> | undefined;
    function refreshIfStale() {
      const loaded = planLoadedRef.current;
      if (Date.now() - loaded.at > PLAN_STALE_MS || localToday() !== loaded.localDate) {
        fetchPlan(initDataRaw).then((data) => !cancelled && applyPlan(data)).catch(() => undefined);
      }
    }
    function scheduleMidnight() {
      const now = new Date();
      const next = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 0, 0, 1);
      midnightTimer = setTimeout(() => {
        refreshIfStale();
        scheduleMidnight();
      }, Math.max(next.getTime() - now.getTime(), 1000));
    }
    function onVisibility() {
      if (document.visibilityState === "visible") {
        refreshIfStale();
      }
    }
    document.addEventListener("visibilitychange", onVisibility);
    scheduleMidnight();
    return () => {
      cancelled = true;
      clearTimeout(midnightTimer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- applyPlan/refresh работают через ref и setPlan.
  }, [initDataRaw]);

  // #288 — после выбора пункта листа, открывающего подтверждение, «⋯» скрыта (или лист закрыт): фокус —
  // на первую кнопку подтверждения (иначе он теряется; на iOS тап по пункту фокус не ставит вообще).
  useEffect(() => {
    if (removeConfirmPlanItemId !== null || removeInclusionConfirmId !== null) {
      document.querySelector<HTMLElement>(".plans-confirm [data-confirm-first]")?.focus();
    }
  }, [removeConfirmPlanItemId, removeInclusionConfirmId]);

  // #288 — подтверждение копирования рисуется под списком недели, часто ниже экрана: показываем и фокусируем «Скопировать».
  useEffect(() => {
    const confirmBlock = copyConfirmRef.current;
    if (copyConfirm && confirmBlock !== null) {
      confirmBlock.scrollIntoView({ block: "center" });
      confirmBlock.querySelector<HTMLElement>("[data-confirm-first]")?.focus({ preventScroll: true });
    }
  }, [copyConfirm]);

  // «Отмена» подтверждения возвращает фокус на «⋯» (она снова в DOM к этому эффекту).
  useEffect(() => {
    if (pendingFocusKey !== null) {
      document.querySelector<HTMLElement>(`[data-focus-key="${pendingFocusKey}"]`)?.focus();
      setPendingFocusKey(null);
    }
  }, [pendingFocusKey]);

  useEffect(() => {
    let cancelled = false;
    fetchPrograms(initDataRaw)
      .then((programs) => {
        if (!cancelled) {
          setCatalogPrograms(programs);
          setCatalogStatus("ready");
        }
      })
      .catch(() => !cancelled && setCatalogStatus("error"));
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  useEffect(() => {
    let cancelled = false;
    fetchExercises(initDataRaw)
      .then((exercises) => {
        if (!cancelled) {
          setExercisesState({ phase: "ready", exercises });
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setExercisesState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  useEffect(() => {
    let cancelled = false;
    fetchDashboard(initDataRaw)
      .then((dashboard) => {
        if (!cancelled) {
          setState({ phase: "ready", dashboard });
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

  // Phase C4a (issue #188) — «Мои тренировки» swap, до loading/error
  // ранних return'ов выше: не зависит от Plans-данных вообще, доступен
  // даже если /api/v2/dashboard ещё грузится/упал.
  if (myWorkoutsView.kind === "custom-plan") {
    return (
      <CustomPlanScreen
        initDataRaw={initDataRaw}
        onBack={() => setMyWorkoutsView({ kind: "closed" })}
        onCreated={() => { setMyWorkoutsView({ kind: "closed" }); reloadPlan(); }}
      />
    );
  }
  if (myWorkoutsView.kind === "list") {
    return (
      <MyWorkoutsScreen
        initDataRaw={initDataRaw}
        onBack={() => setMyWorkoutsView({ kind: "closed" })}
        onCreateWorkout={() => setMyWorkoutsView({ kind: "create" })}
        onOpenWorkout={(workoutId) => setMyWorkoutsView({ kind: "detail", workoutId })}
        onAddToPlan={(workoutId, workoutTitle) =>
          setMyWorkoutsView({ kind: "add-to-plan", workoutId, workoutTitle, returnTo: "list" })}
      />
    );
  }
  if (myWorkoutsView.kind === "add-to-plan") {
    return (
      <AddToPlanScreen
        initDataRaw={initDataRaw}
        workoutId={myWorkoutsView.workoutId}
        workoutTitle={myWorkoutsView.workoutTitle}
        onBack={() => {
          if (myWorkoutsView.returnTo === "edit" || myWorkoutsView.returnTo === "detail") {
            setMyWorkoutsView({ kind: myWorkoutsView.returnTo, workoutId: myWorkoutsView.workoutId });
          } else {
            setMyWorkoutsView({ kind: "list" });
          }
        }}
        onSuccess={() => {
          // issue #188, раздел 10 — переиспользуем уже существующий
          // reloadPlan() (тот же, что "+ Добавить упражнение" вызывает
          // после своего create), не пишем новую логику отрисовки.
          setMyWorkoutsView({ kind: "closed" });
          reloadPlan();
        }}
      />
    );
  }
  if (myWorkoutsView.kind === "move-plan-item") {
    return (
      <MovePlanItemScreen
        initDataRaw={initDataRaw}
        planItemId={myWorkoutsView.planItemId}
        title={myWorkoutsView.title}
        currentDayOfWeek={myWorkoutsView.currentDayOfWeek}
        weeks={plan.weeks.filter((_, index) => isEditableWeek(index, resolveCurrentWeekIndex(plan.weeks, plan.currentWeekId, plan.today ?? localToday())))}
        currentWeekId={myWorkoutsView.planWeekId}
        onBack={() => setMyWorkoutsView({ kind: "closed" })}
        onSuccess={() => {
          setMyWorkoutsView({ kind: "closed" });
          reloadPlan();
        }}
      />
    );
  }
  if (myWorkoutsView.kind === "create") {
    return (
      <WorkoutEditorScreen
        // key: без него React переиспользует тот же instance при переходе
        // create -> edit (одинаковая позиция в дереве), stale internal
        // state (saving) протекает между режимами — найдено живым
        // прогоном (кнопка "Сохранить" оставалась disabled/пустой на
        // Edit-экране сразу после успешного create).
        key="create"
        initDataRaw={initDataRaw}
        workoutId={null}
        onBack={() => setMyWorkoutsView({ kind: "list" })}
        onSaved={(workoutId) => setMyWorkoutsView({ kind: "edit", workoutId })}
        onAddToPlan={() => {}}
        onDeleted={() => setMyWorkoutsView({ kind: "list" })}
        onDuplicated={() => setMyWorkoutsView({ kind: "list" })}
      />
    );
  }
  if (myWorkoutsView.kind === "detail") {
    return (
      <WorkoutDetailScreen
        key={`detail-${myWorkoutsView.workoutId}`}
        initDataRaw={initDataRaw}
        workoutId={myWorkoutsView.workoutId}
        onBack={() => setMyWorkoutsView({ kind: "list" })}
        onEdit={(workoutId) => setMyWorkoutsView({ kind: "edit", workoutId })}
        onAddToPlan={(workoutId, workoutTitle) =>
          setMyWorkoutsView({ kind: "add-to-plan", workoutId, workoutTitle, returnTo: "detail" })}
        onStart={onStartWorkout}
        onLog={onLogWorkout}
        onAddExercise={(workoutId) => setMyWorkoutsView({ kind: "edit", workoutId, openPicker: true })}
      />
    );
  }
  if (myWorkoutsView.kind === "edit") {
    return (
      <WorkoutEditorScreen
        key={`edit-${myWorkoutsView.workoutId}${myWorkoutsView.openPicker ? "-picker" : ""}`}
        startWithPicker={myWorkoutsView.openPicker}
        initDataRaw={initDataRaw}
        workoutId={myWorkoutsView.workoutId}
        onBack={() => setMyWorkoutsView({ kind: "detail", workoutId: myWorkoutsView.workoutId })}
        onSaved={() => setMyWorkoutsView({ kind: "detail", workoutId: myWorkoutsView.workoutId })}
        onAddToPlan={(workoutId, workoutTitle) =>
          setMyWorkoutsView({ kind: "add-to-plan", workoutId, workoutTitle, returnTo: "edit" })}
        onDeleted={() => {
          reloadPlan();
          setMyWorkoutsView({ kind: "list" });
        }}
        onDuplicated={() => setMyWorkoutsView({ kind: "list" })}
      />
    );
  }

  if (state.phase === "loading") {
    return <p className="screen-message">Загружаю…</p>;
  }
  if (state.phase === "error") {
    return <p className="screen-message">Не удалось загрузить: {state.message}</p>;
  }

  const { dashboard } = state;
  const isReady = dashboard.status === "ready";
  // issue #258 — одна неделя за раз. Список — по возрастанию week_number;
  // текущая = последняя начавшаяся (ensure_current_plan_week не создаёт недели
  // наперёд, но будущие недели допустимы — тогда › пойдёт дальше текущей).
  const currentIndex = plan.weeks.length > 0 ? resolveCurrentWeekIndex(plan.weeks, plan.currentWeekId, plan.today ?? localToday()) : 0;
  const currentWeekId = plan.weeks.length > 0 ? plan.weeks[currentIndex].id : null;
  const selectedIndexRaw = plan.weeks.findIndex((week) => week.id === selectedWeekId);
  const selectedIndex = selectedIndexRaw >= 0 ? selectedIndexRaw : currentIndex;
  const visibleWeeks = plan.weeks.length > 0 ? [plan.weeks[selectedIndex]] : [];
  const libraryExercises = exercisesState.phase === "ready" ? exercisesState.exercises : [];
  const courseTint = (programId: number) => {
    const color = programCategoryColorVar(catalogPrograms, programId);
    return color === null ? undefined : ({ ["--cat" as string]: color, ["--cat-ink" as string]: categoryInkVar(color) });
  };
  const activeInclusions = plan.inclusions.filter((i) => i.is_active);
  const finishedInclusions = completedInclusions(plan.inclusions);

  let statusText: string;
  if (isReady && dashboard.is_first_workout) {
    statusText = "Это будет твоя первая тренировка — сначала подберём снаряд по замеру.";
  } else if (isReady) {
    statusText = "Готов к тренировке.";
  } else {
    statusText = STATUS_MESSAGES[dashboard.status] ?? `Статус: ${dashboard.status}`;
  }

  // «Начать» на группе (строка недели и блок «Сегодня» — один и тот же путь).
  function startGroup(group: PlanItemGroup) {
    if (startingGroupKey !== null) {
      return;
    }
    setStartingGroupKey(group.key);
    onStartSession(
      group.items.map((item) => item.id),
      { manual: group.items[0]?.program_inclusion_id === null, title: group.title },
    );
  }
  const groupTint = (group: PlanItemGroup) => {
    const inclusionId = group.items[0]?.program_inclusion_id ?? null;
    const inclusion = inclusionId === null ? undefined : plan.inclusions.find((i) => i.id === inclusionId);
    return inclusion === undefined ? undefined : courseTint(inclusion.program_id);
  };
  const currentWeek = plan.weeks.length > 0 ? plan.weeks[currentIndex] : null;
  // Копировать можно текущую/будущую неделю, если следующая есть или создаётся (как на бэкенде).
  const canCopyWeek = plan.weeks.length > 0
    && isEditableWeek(selectedIndex, currentIndex) && canAdvanceWeek(selectedIndex, plan.weeks.length, currentIndex);
  // «Сегодня» — группы текущей недели на сегодняшний день недели.
  // День недели — от plan.today сервера (дата пользователя), не от часов устройства (#288); вне недели — нет блока.
  const todayIndex = currentWeek === null ? null : todayDayIndexInWeek(currentWeek.start_date, plan.today ?? localToday());
  const todayGroups = currentWeek === null || todayIndex === null || selectedIndex !== currentIndex
    ? []
    : groupPlanItems(
      plan.items.filter((item) => item.plan_week_id === currentWeek.id && item.day_of_week === todayIndex),
      plan.inclusions, libraryExercises,
    );

  function renderSheet() {
    if (sheet === null) {
      return null;
    }
    if (sheet.kind === "row") {
      const actions: SheetAction[] = [
        {
          key: "move", label: "Перенести", testId: "plans-sheet-move",
          onSelect: () => setMyWorkoutsView({
            kind: "move-plan-item", planItemId: sheet.planItemId, title: sheet.title,
            currentDayOfWeek: sheet.dayOfWeek, planWeekId: sheet.planWeekId,
          }),
        },
      ];
      if (sheet.moveOnly) {
        return (
          <ActionSheet
            title={sheet.title} actions={actions} onClose={() => setSheet(null)} testId="plans-row-sheet"
            returnFocusTo={sheetOpener}
          />
        );
      }
      if (sheet.editWorkoutId !== null) {
        const workoutId = sheet.editWorkoutId;
        actions.push({
          key: "edit", label: "Редактировать тренировку", testId: "plans-sheet-edit",
          onSelect: () => setMyWorkoutsView({ kind: "edit", workoutId }),
        });
      }
      actions.push({
        key: "remove", label: "Убрать из плана", danger: true, testId: "plans-sheet-remove",
        onSelect: () => { setRemoveError(null); setRemoveConfirmPlanItemId(sheet.planItemId); },
      });
      return (
        <ActionSheet
          title={sheet.title} actions={actions} onClose={() => setSheet(null)} testId="plans-row-sheet"
          returnFocusTo={sheetOpener}
        />
      );
    }
    // #288 — копирование недели относится к плану, а не к курсу: лист плана («Текущий план») — только оно,
    // лист курса — только «Убрать курс из плана».
    const inclusion = sheet.inclusionId === null ? undefined : activeInclusions.find((i) => i.id === sheet.inclusionId);
    const actions: SheetAction[] = [];
    if (inclusion === undefined && canCopyWeek) {
      const weekNumber = plan.weeks[selectedIndex].week_number;
      actions.push({
        key: "copy", label: `Скопировать неделю ${weekNumber} → ${weekNumber + 1}`, disabled: weekBusy,
        testId: "plans-sheet-copy", onSelect: () => { setCopyConfirm(true); setCopyResult(null); },
      });
    }
    if (inclusion !== undefined) {
      actions.push({
        key: "remove-course", label: "Убрать курс из плана", danger: true, testId: "plans-sheet-remove-course",
        onSelect: () => { setInclusionError(null); setRemoveInclusionConfirmId(inclusion.id); },
      });
    }
    return (
      <ActionSheet
        title={inclusion?.program_name ?? "Текущий план"} actions={actions} onClose={() => setSheet(null)}
        testId="plans-plan-sheet" returnFocusTo={sheetOpener}
      />
    );
  }

  return (
    <div>
      {/* Phase C4a (issue #188) — entry point, не ломает существующую
          навигацию/карточки плана ниже, просто дополнительная кнопка
          сверху экрана. */}
      <div className="screen-title-row">
        <p className="plan-title">Планы</p>
        <Button
          className="action-button" size="s" mode="bezeled"
          onClick={() => setMyWorkoutsView({ kind: "list" })}
        >
          Мои тренировки
        </Button>
      </div>
      {/* issue #304 — минимальный вход «Свой план» (объём по неделям); отдельной строкой — шапка «Планов»
          на 320px уже занята названием и «Мои тренировки». */}
      <div className="plans-custom-plan-entry">
        <Button
          className="action-button" size="s" mode="plain" data-testid="plans-custom-plan"
          onClick={() => setMyWorkoutsView({ kind: "custom-plan" })}
        >
          Свой план по неделям
        </Button>
      </div>
      {plan.customPlans.length > 0 && (
        <Section className="block-section" header="Свои планы">
          {plan.customPlans.map((custom) => (
            <div key={custom.id} className="plans-row-main" data-testid="plans-custom-plan-row" data-active={custom.is_active}>
              <p className="block-subtitle">
                {`${custom.display_name}: ${custom.weeks.map((count, index) => `Н${index + 1} ${count}`).join(" · ")}`}
                {custom.repeat === "cycle" ? " · по кругу" : ""}
                {custom.is_active ? "" : " · остановлен"}
              </p>
              {custom.is_active && (
                <Button
                  size="s" mode="outline" data-testid="plans-custom-plan-stop"
                  disabled={stoppingCustomPlanId !== null}
                  onClick={() => void handleStopCustomPlan(custom.id, custom.display_name)}
                >
                  {stoppingCustomPlanId === custom.id ? "Останавливаю…" : "Остановить план"}
                </Button>
              )}
            </div>
          ))}
          {customPlanError && <p className="gap-banner">{customPlanError}</p>}
        </Section>
      )}
      <div className="workout-mode-buttons vp-tabs plans-tabs" role="tablist" aria-label="Обзор плана">
        {([["now", "Сейчас"], ["completed", "Завершённые"]] as const).map(([key, label]) => (
          <button
            key={key} type="button" role="tab" aria-selected={overviewTab === key}
            className={overviewTab === key ? "leaderboard-tab leaderboard-tab-active" : "leaderboard-tab"}
            onClick={() => setOverviewTab(key)}
          >
            {label}
          </button>
        ))}
      </div>
      {overviewTab === "completed" && (
        <div className="profile-card" data-testid="plans-completed">
          {finishedInclusions.length === 0 && (
            <p className="block-subtitle" data-testid="plans-completed-empty">
              Завершённых курсов пока нет. Убранные из плана курсы появятся здесь.
            </p>
          )}
          {finishedInclusions.map((inclusion) => (
            <div
              key={inclusion.id} className="plan-week-day-group plans-course" data-testid="plans-completed-row"
              style={courseTint(inclusion.program_id)}
            >
              <p className="plan-item-row">{inclusion.program_name}</p>
              <p className="block-subtitle">{inclusionDateRange(inclusion)}</p>
            </div>
          ))}
        </div>
      )}
      {overviewTab === "now" && (
        <div className="profile-card" data-testid="plans-now-card">
          <div className="plans-card-head">
            <p className="block-subtitle">Текущий план</p>
            {canCopyWeek && (
              <MoreButton
                label="Действия: Текущий план" testId="plans-card-more" focusKey="plan"
                onClick={(opener) => openSheet({ kind: "plan", inclusionId: null }, opener)}
              />
            )}
          </div>
          {activeInclusions.length === 0 && (
            <>
              {catalogStatus === "ready" && catalogPrograms.length === 0 ? (
                <p className="block-subtitle" data-testid="plans-now-empty">
                  Курсов для подключения пока нет — каталог пуст. Соберите свою тренировку: она появится в плане, когда вы добавите её на день.
                </p>
              ) : catalogStatus === "error" ? (
                <p className="block-subtitle" data-testid="plans-now-empty">
                  Не удалось загрузить каталог курсов. Попробуйте позже или соберите свою тренировку.
                </p>
              ) : (
                <p className="block-subtitle" data-testid="plans-now-empty">
                  Курсов в плане нет. Добавьте курс на Главной.
                </p>
              )}
              {catalogStatus === "ready" && catalogPrograms.length > 0 && onOpenHome !== undefined && (
                <Button size="s" mode="outline" data-testid="plans-now-open-home" onClick={onOpenHome}>
                  Выбрать курс на Главной
                </Button>
              )}
              {catalogStatus !== "loading" && !(catalogStatus === "ready" && catalogPrograms.length > 0) && (
                <Button size="s" mode="outline" data-testid="plans-now-create-workout" onClick={() => setMyWorkoutsView({ kind: "create" })}>
                  Создать тренировку
                </Button>
              )}
            </>
          )}
          {activeInclusions.map((inclusion) => {
            const currentItems = plan.items.filter(
              (item) => item.program_inclusion_id === inclusion.id && item.plan_week_id === currentWeekId,
            );
            const progress = weekProgress(
              groupPlanItems(currentItems, plan.inclusions, libraryExercises).map((group) => group.items),
            );
            const weekLabel = inclusionWeekLabel(inclusion);
            const confirming = removeInclusionConfirmId === inclusion.id;
            const removing = removingInclusionId === inclusion.id;
            return (
              <div
                key={inclusion.id} className="plan-week-day-group plans-course" data-testid="plans-now-inclusion"
                style={courseTint(inclusion.program_id)}
              >
                <div className="plans-course-head">
                  <div className="plans-course-text">
                    <p className="plan-item-row">{inclusion.program_name}</p>
                    <p className="block-subtitle">
                      {weekLabel ? `${weekLabel} · ` : ""}
                      <span data-testid="plans-now-progress">{`На этой неделе: ${progress.done} из ${progress.total}`}</span>
                    </p>
                  </div>
                  {!confirming && (
                    <MoreButton
                      label={`Действия: ${inclusion.program_name}`} testId="plans-plan-more" focusKey={`course-${inclusion.id}`}
                      onClick={(opener) => openSheet({ kind: "plan", inclusionId: inclusion.id }, opener)}
                    />
                  )}
                </div>
                <PlanProgressBar
                  done={progress.done} total={progress.total} percent={progressPercent(progress.done, progress.total)}
                  label={`Прогресс недели: ${inclusion.program_name}`} testId="plans-now-progressbar"
                />
                {confirming && (
                  <div className="plans-confirm">
                    <p className="block-subtitle">
                      Убрать курс «{inclusion.program_name}» из плана? История сохранится.
                    </p>
                    {inclusionError && <p className="gap-banner">{inclusionError}</p>}
                    <div className="plans-confirm-actions">
                      <Button
                        size="s" mode="outline" disabled={removing} data-confirm-first="true"
                        onClick={() => void handleRemoveInclusion(inclusion.id)}
                      >
                        {removing ? "Убираю…" : "Убрать"}
                      </Button>
                      <Button
                        size="s" mode="outline" disabled={removing}
                        onClick={() => {
                          setRemoveInclusionConfirmId(null);
                          setInclusionError(null);
                          setPendingFocusKey(`course-${inclusion.id}`);
                        }}
                      >
                        Отмена
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {overviewTab === "now" && todayGroups.length > 0 && (
        <section className="profile-card plans-today" data-testid="plans-today" aria-labelledby="plans-today-title">
          <h2 id="plans-today-title" className="plans-today-title">Сегодня</h2>
          {todayGroups.map((group) => {
            const counter = groupCounter(group.items);
            const todayDone = counter.planned > 0 && counter.done >= counter.planned;
            return (
              <div key={group.key} className="plans-row-main" data-testid="plans-today-row" data-done={todayDone} style={groupTint(group)}>
                <span className="plans-row-bar" aria-hidden="true" />
                <div className="plans-row-text">
                  <span className="plans-row-title">{group.title}</span>
                  <span className="plans-row-chip" data-done={todayDone}>
                    {`${counter.done}/${counter.planned}`}
                  </span>
                </div>
                {todayDone ? (
                  <button
                    type="button" className="plans-start plans-start-again" aria-label={`Повторить: ${group.title}`}
                    disabled={startingGroupKey !== null} onClick={() => startGroup(group)}
                  >
                    {startingGroupKey === group.key ? "Начинаю…" : "Ещё раз"}
                  </button>
                ) : (
                  <button
                    type="button" className="plans-start" aria-label={`Начать: ${group.title}`}
                    disabled={startingGroupKey !== null} onClick={() => startGroup(group)}
                  >
                    {startingGroupKey === group.key ? "Начинаю…" : "Начать"}
                  </button>
                )}
              </div>
            );
          })}
        </section>
      )}
      {overviewTab === "now" && visibleWeeks.length > 0 && (
        <>
          {visibleWeeks.map((week) => {
            const isCurrent = week.id === currentWeekId;
            const isEditable = isEditableWeek(selectedIndex, currentIndex);
            const weekItems = plan.items.filter((item) => item.plan_week_id === week.id);
            const freePool = weekItems.filter((item) => item.day_of_week === null);
            const byDay = new Map<number, PlanItemResponseV2[]>();
            for (const item of weekItems) {
              if (item.day_of_week === null) {
                continue;
              }
              const dayItems = byDay.get(item.day_of_week) ?? [];
              dayItems.push(item);
              byDay.set(item.day_of_week, dayItems);
            }
            const days = [...byDay.entries()].sort(([a], [b]) => a - b);
            // #301 — намеренная REST-неделя без строк говорит об этом явно, а не голым «0 из 0».
            const isRestWeek = week.phase === "rest" && weekItems.length === 0;
            const weekProgressValue = weekProgress(
              groupPlanItems(weekItems, plan.inclusions, libraryExercises).map((group) => group.items),
            );

            // Checkpoint 4A/4B (issue #188) — "Начать" на любой группе
            // текущей недели (program-backed ИЛИ manual), тот же принцип,
            // что уже ограничивает "+ Добавить упражнение" ниже —
            // isCurrent, не тип группы.
            function renderGroupRow(group: PlanItemGroup) {
              const isProgramBacked = group.items[0]?.program_inclusion_id !== null;
              // Phase D3 (issue #188) — Move/Remove/Edit доступны только
              // для НЕ program-backed групп (раздел 10 — "STEP-group...
              // Move/Remove/Edit отсутствуют полностью"). Такие группы
              // всегда состоят ровно из одного PlanItem (groupPlanItems
              // не объединяет manual/user-Workout строки друг с другом,
              // докстринг PlanItem), поэтому group.items[0] — единственный
              // и весь предмет действия, не случайный выбор из нескольких.
              // #286 B — эти действия теперь в листе «⋯» (одна кнопка на строке).
              const mutableItem = !isProgramBacked ? group.items[0] : null;
              // issue #304 (PL6): занятие курса переносится (неделя/день), но не удаляется отдельно.
              const occurrence = group.items.length === 1 && group.items[0].occurrence_index != null ? group.items[0] : null;
              const movableCourseItem = isProgramBacked && occurrence !== null && occurrence.state !== "completed"
                ? occurrence : null;
              const stateLabel = occurrence === null ? null : occurrenceStateLabel(occurrence);
              // §6: будущие недели видимы И стартуемы; K1 (отдых) решает сервер — «рано» не стартуем.
              const canStart = (isCurrent || selectedIndex > currentIndex) && !(occurrence?.legacy_aggregate)
                && occurrence?.state !== "too_early";
              const isRemoveConfirming = mutableItem !== null && removeConfirmPlanItemId === mutableItem.id;
              const isRemoving = mutableItem !== null && removingPlanItemId === mutableItem.id;
              const canEditWorkout = mutableItem !== null
                && mutableItem.complex_id !== null && mutableItem.complex_source_type === "user";
              const counter = groupCounter(group.items);
              // #288 — имя для скринридера: название + день (одинаковые названия в разные дни различимы).
              const rowDay = group.items[0]?.day_of_week ?? null;
              const rowDone = counter.planned > 0 && counter.done >= counter.planned;
              const rowLabel = `${group.title}, ${rowDay === null ? "без дня" : (DAY_NAMES[rowDay] ?? `день ${rowDay}`).toLowerCase()}`;
              return (
                <div key={group.key} className="plan-week-day-group plans-row" data-testid="plans-row" data-done={rowDone} style={groupTint(group)}>
                  <div className="plans-row-main">
                    <span className="plans-row-bar" aria-hidden="true" />
                    <div className="plans-row-text">
                      <span className="plans-row-title">{group.title}</span>
                      <span className="plans-row-chip" data-done={rowDone} data-testid="plan-item-counter">
                        {`${counter.done}/${counter.planned}`}
                      </span>
                      {stateLabel !== null && (
                        <span className="plans-row-scheduled block-subtitle" data-testid="plans-row-state" data-state={occurrence?.state ?? ""}>
                          {stateLabel}
                        </span>
                      )}
                    </div>
                    {canStart && (
                      rowDone ? (
                        <button
                          type="button" className="plans-start plans-start-again" aria-label={`Повторить: ${rowLabel}`}
                          data-testid="plans-row-again" disabled={startingGroupKey !== null} onClick={() => startGroup(group)}
                        >
                          {startingGroupKey === group.key ? "Начинаю…" : "Ещё раз"}
                        </button>
                      ) : (
                        <button
                          type="button" className="plans-start" aria-label={`Начать: ${rowLabel}`}
                          disabled={startingGroupKey !== null} onClick={() => startGroup(group)}
                        >
                          {startingGroupKey === group.key ? "Начинаю…" : "Начать"}
                        </button>
                      )
                    )}
                    {isEditable && movableCourseItem !== null && (
                      <MoreButton
                        label={`Действия: ${rowLabel}`} testId="plans-row-more" focusKey={`row-${movableCourseItem.id}`}
                        onClick={(opener) => openSheet({
                          kind: "row", planItemId: movableCourseItem.id, title: group.title,
                          dayOfWeek: movableCourseItem.day_of_week, planWeekId: movableCourseItem.plan_week_id,
                          editWorkoutId: null, moveOnly: true,
                        }, opener)}
                      />
                    )}
                    {isEditable && mutableItem !== null && !isRemoveConfirming && (
                      <MoreButton
                        label={`Действия: ${rowLabel}`} testId="plans-row-more" focusKey={`row-${mutableItem.id}`}
                        onClick={(opener) => openSheet({
                          kind: "row", planItemId: mutableItem.id, title: group.title,
                          dayOfWeek: mutableItem.day_of_week, planWeekId: mutableItem.plan_week_id,
                          editWorkoutId: canEditWorkout ? mutableItem.complex_id : null,
                        }, opener)}
                      />
                    )}
                  </div>
                  {isEditable && mutableItem !== null && isRemoveConfirming && (
                    <div className="plans-confirm">
                      <p className="block-subtitle">Убрать «{group.title}» из плана?</p>
                      {removeError && <p className="gap-banner">{removeError}</p>}
                      <div className="plans-confirm-actions">
                        <Button
                          size="s" mode="outline" disabled={isRemoving} data-confirm-first="true"
                          onClick={() => void handleRemovePlanItem(mutableItem.id)}
                        >
                          {isRemoving ? "Убираю…" : "Убрать"}
                        </Button>
                        <Button
                          size="s" mode="outline" disabled={isRemoving}
                          onClick={() => { setRemoveConfirmPlanItemId(null); setPendingFocusKey(`row-${mutableItem.id}`); }}
                        >
                          Отмена
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              );
            }

            return (
              <Section
                key={week.id}
                className={isCurrent ? "block-section plans-week-card plan-week-current" : "block-section plans-week-card plan-week-past"}
              >
                <div className="plan-week-stepper" data-testid="plan-week-stepper">
                  <button
                    type="button" aria-label="Предыдущая неделя" className="plan-week-step"
                    disabled={selectedIndex === 0}
                    onClick={() => {
                      setCopyConfirm(false);
                      setCopyResult(null);
                      setSelectedWeekId(plan.weeks[stepWeek(selectedIndex, -1, plan.weeks.length)].id);
                    }}
                  >
                    ‹
                  </button>
                  <div className="plan-week-stepper-label">
                    <span data-testid="plan-week-label">
                      {`Неделя ${week.week_number} · ${weekRangeLabel(week.start_date)}`}
                    </span>
                    <span className="plan-week-chip">{WEEK_PHASE_LABELS[week.phase] ?? week.phase}</span>
                  </div>
                  <button
                    type="button" aria-label="Следующая неделя" className="plan-week-step"
                    disabled={weekBusy || !canAdvanceWeek(selectedIndex, plan.weeks.length, currentIndex)}
                    onClick={() => {
                      setCopyConfirm(false);
                      setCopyResult(null);
                      if (selectedIndex >= plan.weeks.length - 1) {
                        void handleAdvanceWeek(week);
                      } else {
                        setSelectedWeekId(plan.weeks[stepWeek(selectedIndex, 1, plan.weeks.length)].id);
                      }
                    }}
                  >
                    ›
                  </button>
                </div>
                <p className="block-subtitle" data-testid="plan-week-progress">
                  {isCurrent ? "Текущая неделя · " : ""}
                  {isRestWeek ? "Неделя отдыха" : `${weekProgressValue.done} из ${weekProgressValue.total}`}
                </p>
                <PlanProgressBar
                  done={weekProgressValue.done} total={weekProgressValue.total}
                  percent={progressPercent(weekProgressValue.done, weekProgressValue.total)}
                  label="Прогресс недели" testId="plan-week-progressbar"
                />
                {isCurrent && !isReady && (
                  <p className="block-subtitle" style={{ marginBottom: "12px" }}>{statusText}</p>
                )}
                {weekItems.length === 0 && (
                  <p className="block-subtitle">
                    {isRestWeek
                      ? "По плану на этой неделе отдых — тренировок нет."
                      : isEditable
                        ? "На эту неделю пока ничего не запланировано."
                        : "На этой неделе ничего не было запланировано."}
                  </p>
                )}
                {days.map(([day, dayItems]) => (
                  <div key={day} className="plan-week-day-group">
                    <p className="block-subtitle">{DAY_NAMES[day] ?? `День ${day}`}</p>
                    {groupPlanItems(dayItems, plan.inclusions, libraryExercises).map(renderGroupRow)}
                  </div>
                ))}
                {freePool.length > 0 && (
                  <div className="plan-week-day-group">
                    <p className="block-subtitle">Свободный пул</p>
                    {groupPlanItems(freePool, plan.inclusions, libraryExercises).map(renderGroupRow)}
                  </div>
                )}
                {isEditable && (
                  <div className="plan-week-day-group">
                    <button
                      type="button"
                      className="program-card-button plan-add-exercise-button"
                      onClick={() => handleAddExercise(week.id)}
                    >
                      + Добавить упражнение
                    </button>
                  </div>
                )}
                {copyConfirm && isEditable && canAdvanceWeek(selectedIndex, plan.weeks.length, currentIndex) && (
                  <div ref={copyConfirmRef} className="plan-week-day-group" data-testid="plan-week-copy">
                    <p className="block-subtitle">
                      Скопировать свои тренировки и упражнения этой недели в следующую? Дубли пропустим.
                    </p>
                    <div className="plans-confirm-actions">
                      <Button
                        size="s" mode="outline" disabled={weekBusy} data-confirm-first="true"
                        onClick={() => void handleCopyWeek(week.id)}
                      >
                        {weekBusy ? "Копирую…" : "Скопировать"}
                      </Button>
                      <Button
                        size="s" mode="outline" disabled={weekBusy}
                        onClick={() => { setCopyConfirm(false); setPendingFocusKey("plan"); }}
                      >
                        Отмена
                      </Button>
                    </div>
                  </div>
                )}
                {copyResult && <p className="block-subtitle" role="status" data-testid="plan-week-copy-result">{copyResult}</p>}
                {weekError && <p className="gap-banner">{weekError}</p>}
              </Section>
            );
          })}
        </>
      )}
      {renderSheet()}

      {picker.phase !== "closed" && (
        <Section className="block-section" header="Добавить упражнение">
          {exercisesState.phase === "loading" && <p className="screen-message">Загружаю библиотеку…</p>}
          {exercisesState.phase === "error" && (
            <p className="screen-message">Не удалось загрузить упражнения: {exercisesState.message}</p>
          )}
          {exercisesState.phase === "ready" && (
            <div className="plan-week-day-group">
              {exercisesState.exercises.map((exercise) => (
                <button
                  key={exercise.id}
                  type="button"
                  disabled={picker.phase === "adding"}
                  className={
                    picker.exerciseId === exercise.id
                      ? "program-card-button plan-exercise-option plan-exercise-option-selected"
                      : "program-card-button plan-exercise-option"
                  }
                  onClick={() => updatePickerSelection({ exerciseId: exercise.id })}
                >
                  {exercise.name}
                </button>
              ))}
            </div>
          )}

          <p className="block-subtitle">День</p>
          <div className="plan-week-day-group">
            <button
              type="button"
              disabled={picker.phase === "adding"}
              className={
                picker.day === null
                  ? "program-card-button plan-exercise-option plan-exercise-option-selected"
                  : "program-card-button plan-exercise-option"
              }
              onClick={() => updatePickerSelection({ day: null })}
            >
              Свободный пул
            </button>
            {DAY_NAMES.map((name, dayIndex) => (
              <button
                key={dayIndex}
                type="button"
                disabled={picker.phase === "adding"}
                className={
                  picker.day === dayIndex
                    ? "program-card-button plan-exercise-option plan-exercise-option-selected"
                    : "program-card-button plan-exercise-option"
                }
                onClick={() => updatePickerSelection({ day: dayIndex })}
              >
                {name}
              </button>
            ))}
          </div>

          {picker.phase === "add-error" && (
            <p className="screen-message">Не удалось добавить: {picker.message}</p>
          )}

          <Button
            className="action-button" size="m" stretched
            disabled={picker.exerciseId === null || picker.phase === "adding"}
            onClick={handleConfirmAdd}
          >
            {picker.phase === "adding" ? "Добавляю…" : "Добавить"}
          </Button>
          <Button mode="outline" size="s" disabled={picker.phase === "adding"} onClick={() => setPicker({ phase: "closed" })}>
            Отмена
          </Button>
        </Section>
      )}
    </div>
  );
}
