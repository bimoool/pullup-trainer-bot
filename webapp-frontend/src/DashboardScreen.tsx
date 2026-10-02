import { Button, Section } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchDashboard, type DashboardResponse } from "./api";
import {
  copyPlanWeekToNext,
  createPlanItem,
  createPlanWeek,
  type ExerciseResponseV2,
  fetchExercises,
  fetchPlan,
  type PlanItemResponseV2,
  type PlanWeekResponseV2,
  type ProgramInclusionResponseV2,
  removePlanItem,
  deactivateProgramInclusion,
  type TrainingPlanResponseV2,
} from "./apiV2";
import { completedInclusions, inclusionDateRange, inclusionWeekLabel } from "./plansOverview";
import { STATUS_MESSAGES } from "./WorkoutScreen";
import { AddToPlanScreen } from "./AddToPlanScreen";
import { MovePlanItemScreen } from "./MovePlanItemScreen";
import { MyWorkoutsScreen } from "./MyWorkoutsScreen";
import { WorkoutDetailScreen } from "./WorkoutDetailScreen";
import { WorkoutEditorScreen } from "./WorkoutEditorScreen";
import {
  canAdvanceWeek, groupCounter, isEditableWeek, localToday, resolveCurrentWeekIndex, stepWeek, weekProgress, weekRangeLabel,
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
  return `🔥 ${streak}`;
}

type PlanState = {
  inclusions: ProgramInclusionResponseV2[];
  items: PlanItemResponseV2[];
  weeks: PlanWeekResponseV2[];
  /** current_week_id с сервера (часовой пояс пользователя). */
  currentWeekId: number | null;
};

const EMPTY_PLAN: PlanState = { inclusions: [], items: [], weeks: [], currentWeekId: null };

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
  };
}

// Phase C4a/C5a/D3 (issue #188) — «Мои тренировки» + Plans card actions
// swap-state.
type MyWorkoutsView =
  | { kind: "closed" }
  | { kind: "list" }
  | { kind: "create" }
  | { kind: "detail"; workoutId: number }
  | { kind: "edit"; workoutId: number }
  | { kind: "add-to-plan"; workoutId: number; workoutTitle: string; returnTo: "list" | "edit" | "detail" }
  | { kind: "move-plan-item"; planItemId: number; title: string; currentDayOfWeek: number | null; planWeekId: number | null };

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
export function DashboardScreen({ initDataRaw, onStartSession, onStartWorkout, onLogWorkout }: Props) {
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
  const [myWorkoutsView, setMyWorkoutsView] = useState<MyWorkoutsView>({ kind: "closed" });
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
  const [inclusionError, setInclusionError] = useState<string | null>(null);

  // issue #275 — планирование вперёд: › за последней неделей создаёт следующую;
  // «Скопировать неделю» — с подтверждением.
  const [weekBusy, setWeekBusy] = useState(false);
  const [weekError, setWeekError] = useState<string | null>(null);
  const [copyConfirm, setCopyConfirm] = useState(false);
  const [copyResult, setCopyResult] = useState<string | null>(null);

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

  function reloadPlan() {
    return fetchPlan(initDataRaw).then((data) => {
      setPlan(toPlanState(data));
    });
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
          setPlan(toPlanState(data));
        }
      })
      .catch(() => {
        // молчаливо — см. комментарий у объявления state выше
      });
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
        weeks={plan.weeks.filter((_, index) => isEditableWeek(index, resolveCurrentWeekIndex(plan.weeks, plan.currentWeekId, localToday())))}
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
      />
    );
  }
  if (myWorkoutsView.kind === "edit") {
    return (
      <WorkoutEditorScreen
        key={`edit-${myWorkoutsView.workoutId}`}
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
  const currentIndex = plan.weeks.length > 0 ? resolveCurrentWeekIndex(plan.weeks, plan.currentWeekId, localToday()) : 0;
  const currentWeekId = plan.weeks.length > 0 ? plan.weeks[currentIndex].id : null;
  const selectedIndexRaw = plan.weeks.findIndex((week) => week.id === selectedWeekId);
  const selectedIndex = selectedIndexRaw >= 0 ? selectedIndexRaw : currentIndex;
  const visibleWeeks = plan.weeks.length > 0 ? [plan.weeks[selectedIndex]] : [];
  const libraryExercises = exercisesState.phase === "ready" ? exercisesState.exercises : [];
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

  return (
    <div>
      {/* Phase C4a (issue #188) — entry point, не ломает существующую
          навигацию/карточки плана ниже, просто дополнительная кнопка
          сверху экрана. */}
      <Button
        className="action-button" size="m"
        onClick={() => setMyWorkoutsView({ kind: "list" })}
      >
        Мои тренировки
      </Button>
      <div className="workout-mode-buttons" role="tablist" aria-label="Обзор плана">
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
            <div key={inclusion.id} className="plan-week-day-group" data-testid="plans-completed-row">
              <p className="plan-item-row">{inclusion.program_name}</p>
              <p className="block-subtitle">{inclusionDateRange(inclusion)}</p>
            </div>
          ))}
        </div>
      )}
      {overviewTab === "now" && (
        <div className="profile-card" data-testid="plans-now-card">
          <p className="block-subtitle">Текущий план</p>
          {activeInclusions.length === 0 && (
            <p className="block-subtitle" data-testid="plans-now-empty">
              Курсов в плане нет. Добавьте курс на Главной.
            </p>
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
              <div key={inclusion.id} className="plan-week-day-group" data-testid="plans-now-inclusion">
                <p className="plan-item-row">{inclusion.program_name}</p>
                <p className="block-subtitle">
                  {weekLabel ? `${weekLabel} · ` : ""}
                  <span data-testid="plans-now-progress">{`На этой неделе: ${progress.done} из ${progress.total}`}</span>
                </p>
                {!confirming && (
                  <Button size="s" mode="outline" onClick={() => setRemoveInclusionConfirmId(inclusion.id)}>
                    Убрать курс из плана
                  </Button>
                )}
                {confirming && (
                  <>
                    <p className="block-subtitle">
                      Убрать курс «{inclusion.program_name}» из плана? История сохранится.
                    </p>
                    {inclusionError && <p className="gap-banner">{inclusionError}</p>}
                    <Button
                      size="s" mode="outline" disabled={removing}
                      onClick={() => void handleRemoveInclusion(inclusion.id)}
                    >
                      {removing ? "Убираю…" : "Убрать"}
                    </Button>
                    <Button
                      size="s" mode="outline" disabled={removing}
                      onClick={() => { setRemoveInclusionConfirmId(null); setInclusionError(null); }}
                    >
                      Отмена
                    </Button>
                  </>
                )}
              </div>
            );
          })}
        </div>
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
              const mutableItem = !isProgramBacked ? group.items[0] : null;
              const isRemoveConfirming = mutableItem !== null && removeConfirmPlanItemId === mutableItem.id;
              const isRemoving = mutableItem !== null && removingPlanItemId === mutableItem.id;
              const canEditWorkout = mutableItem !== null
                && mutableItem.complex_id !== null && mutableItem.complex_source_type === "user";
              return (
                <div key={group.key} className="plan-week-day-group">
                  <p className="plan-item-row">
                    {group.title}
                    {" · "}
                    <span data-testid="plan-item-counter">
                      {`${groupCounter(group.items).done}/${groupCounter(group.items).planned}`}
                    </span>
                  </p>
                  {isCurrent && (
                    <button
                      type="button"
                      className="program-card-button plan-add-exercise-button"
                      disabled={startingGroupKey !== null}
                      onClick={() => {
                        if (startingGroupKey !== null) {
                          return;
                        }
                        setStartingGroupKey(group.key);
                        onStartSession(
                          group.items.map((item) => item.id),
                          { manual: !isProgramBacked, title: group.title },
                        );
                      }}
                    >
                      {startingGroupKey === group.key ? "Начинаю…" : "Начать"}
                    </button>
                  )}
                  {isEditable && mutableItem !== null && !isRemoveConfirming && (
                    <>
                      <Button
                        size="s" mode="outline"
                        onClick={() => setMyWorkoutsView({
                          kind: "move-plan-item", planItemId: mutableItem.id,
                          title: group.title, currentDayOfWeek: mutableItem.day_of_week,
                          planWeekId: mutableItem.plan_week_id,
                        })}
                      >
                        Перенести
                      </Button>
                      <Button size="s" mode="outline" onClick={() => setRemoveConfirmPlanItemId(mutableItem.id)}>
                        Убрать из плана
                      </Button>
                      {canEditWorkout && (
                        <Button
                          size="s" mode="outline"
                          onClick={() => setMyWorkoutsView({ kind: "edit", workoutId: mutableItem.complex_id! })}
                        >
                          Редактировать тренировку
                        </Button>
                      )}
                    </>
                  )}
                  {isEditable && mutableItem !== null && isRemoveConfirming && (
                    <>
                      <p className="block-subtitle">Убрать «{group.title}» из плана?</p>
                      {removeError && <p className="gap-banner">{removeError}</p>}
                      <Button
                        size="s" mode="outline" disabled={isRemoving}
                        onClick={() => void handleRemovePlanItem(mutableItem.id)}
                      >
                        {isRemoving ? "Убираю…" : "Убрать"}
                      </Button>
                      <Button size="s" mode="outline" disabled={isRemoving} onClick={() => setRemoveConfirmPlanItemId(null)}>
                        Отмена
                      </Button>
                    </>
                  )}
                </div>
              );
            }

            return (
              <Section
                key={week.id}
                className={isCurrent ? "block-section plan-week-current" : "block-section plan-week-past"}
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
                  {`${weekProgressValue.done} из ${weekProgressValue.total}`}
                </p>
                {isCurrent && !isReady && (
                  <p className="block-subtitle" style={{ marginBottom: "12px" }}>{statusText}</p>
                )}
                {weekItems.length === 0 && (
                  <p className="block-subtitle">На эту неделю пока ничего не запланировано.</p>
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
                {isEditable && canAdvanceWeek(selectedIndex, plan.weeks.length, currentIndex) && (
                  <div className="plan-week-day-group" data-testid="plan-week-copy">
                    {!copyConfirm ? (
                      <button
                        type="button" className="program-card-button plan-add-exercise-button"
                        disabled={weekBusy}
                        onClick={() => { setCopyConfirm(true); setCopyResult(null); }}
                      >
                        Скопировать неделю → на следующую
                      </button>
                    ) : (
                      <>
                        <p className="block-subtitle">
                          Скопировать свои тренировки и упражнения этой недели в следующую? Дубли пропустим.
                        </p>
                        <Button size="s" mode="outline" disabled={weekBusy} onClick={() => void handleCopyWeek(week.id)}>
                          {weekBusy ? "Копирую…" : "Скопировать"}
                        </Button>
                        <Button size="s" mode="outline" disabled={weekBusy} onClick={() => setCopyConfirm(false)}>
                          Отмена
                        </Button>
                      </>
                    )}
                  </div>
                )}
                {copyResult && <p className="block-subtitle" data-testid="plan-week-copy-result">{copyResult}</p>}
                {weekError && <p className="gap-banner">{weekError}</p>}
              </Section>
            );
          })}
        </>
      )}

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
