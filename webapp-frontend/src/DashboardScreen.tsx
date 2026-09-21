import { Button, Section } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchDashboard, type DashboardResponse } from "./api";
import {
  createPlanItem,
  type ExerciseResponseV2,
  fetchExercises,
  fetchPlan,
  type PlanItemResponseV2,
  type PlanWeekResponseV2,
  type ProgramInclusionResponseV2,
} from "./apiV2";
import { STATUS_MESSAGES } from "./WorkoutScreen";

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
};

const EMPTY_PLAN: PlanState = { inclusions: [], items: [], weeks: [] };

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
export function DashboardScreen({ initDataRaw, onStartSession }: Props) {
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

  function reloadPlan() {
    return fetchPlan(initDataRaw).then((data) => {
      setPlan(
        data === null
          ? EMPTY_PLAN
          : {
              inclusions: data.program_inclusions.filter((i) => i.is_active),
              items: data.plan_items,
              weeks: data.plan_weeks,
            },
      );
    });
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
          setPlan(
            data === null
              ? EMPTY_PLAN
              : {
                  inclusions: data.program_inclusions.filter((i) => i.is_active),
                  items: data.plan_items,
                  weeks: data.plan_weeks,
                },
          );
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

  if (state.phase === "loading") {
    return <p className="screen-message">Загружаю…</p>;
  }
  if (state.phase === "error") {
    return <p className="screen-message">Не удалось загрузить: {state.message}</p>;
  }

  const { dashboard } = state;
  const isReady = dashboard.status === "ready";
  // Последняя неделя списка — всегда текущая: list_plan_weeks сортирует по
  // возрастанию week_number, а ensure_current_plan_week (issue #188,
  // вызывается на каждый GET /api/v2/plan) никогда не создаёт недели
  // наперёд, только текущую календарную. Показ — от текущей к прошлым
  // (тот же порядок "свежее сверху", что и в HistoryScreen.tsx).
  const currentWeekId = plan.weeks.length > 0 ? plan.weeks[plan.weeks.length - 1].id : null;
  const weeksNewestFirst = [...plan.weeks].reverse();
  const libraryExercises = exercisesState.phase === "ready" ? exercisesState.exercises : [];

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
      {weeksNewestFirst.length > 0 && (
        <>
          {weeksNewestFirst.map((week) => {
            const isCurrent = week.id === currentWeekId;
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

            // Checkpoint 4A/4B (issue #188) — "Начать" на любой группе
            // текущей недели (program-backed ИЛИ manual), тот же принцип,
            // что уже ограничивает "+ Добавить упражнение" ниже —
            // isCurrent, не тип группы.
            function renderGroupRow(group: PlanItemGroup) {
              const isProgramBacked = group.items[0]?.program_inclusion_id !== null;
              return (
                <div key={group.key} className="plan-week-day-group">
                  <p className="plan-item-row">
                    {group.title}
                    {group.items.length === 1 && ` · ${group.items[0].count_per_week}×/нед`}
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
                </div>
              );
            }

            return (
              <Section
                key={week.id}
                className={isCurrent ? "block-section plan-week-current" : "block-section plan-week-past"}
                header={
                  `Неделя ${week.week_number}${isCurrent ? " · текущая" : ""} · `
                  + `${WEEK_PHASE_LABELS[week.phase] ?? week.phase}`
                }
              >
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
                {isCurrent && (
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
