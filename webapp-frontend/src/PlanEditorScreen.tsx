import { Button, Section } from "@telegram-apps/telegram-ui";
import { useCallback, useEffect, useState } from "react";

import {
  addPlanWorkout, deletePlanWeek, fetchPlanEditor, insertPlanWeek, listSystemWorkouts, listWorkouts,
  removePlanWorkout, setWeekPhase, setWeekQuantities, type CustomPlanEditorV2, type EditorWeekV2,
  type WorkoutResponseV2,
} from "./apiV2";
import { FormSheet } from "./FormSheet";
import { PHASE_LABELS, nextPhase, quantityBounds, weekEmptyNote } from "./planEditorMath";
import { weekRangeLabel } from "./planWeekNav";
import { useBackButton } from "./useBackButton";

// UX-EDITOR (UX-24/12/28): количество каждой тренировки по неделям, фазы, итоги, вставка/удаление недель.
// Дни назначаются отдельно (WeekScheduleScreen). Каждое разрушительное действие — в листе-подтверждении
// (не window.confirm) с названием того, что будет потеряно. Отличия от референса: нет фазы «Build», нет
// часов (длительность не выдумываем), только целые количества.

type Props = {
  initDataRaw: string;
  planId: number;
  onBack: () => void;
  onOpenSchedule: (index: number) => void;
};

type Confirm =
  | { kind: "delete-week"; index: number }
  | { kind: "remove-workout"; workoutId: number; title: string }
  | null;

export function PlanEditorScreen({ initDataRaw, planId, onBack, onOpenSchedule }: Props) {
  const [plan, setPlan] = useState<CustomPlanEditorV2 | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [adding, setAdding] = useState<WorkoutResponseV2[] | null>(null);

  const close = useCallback(() => { if (!busy) { onBack(); } }, [busy, onBack]);
  useBackButton(close, [close], true, false);

  useEffect(() => {
    let cancelled = false;
    fetchPlanEditor(initDataRaw, planId)
      .then((data) => { if (!cancelled) { setPlan(data); } })
      .catch((reason) => { if (!cancelled) { setError(reason instanceof Error ? reason.message : String(reason)); } });
    return () => { cancelled = true; };
  }, [initDataRaw, planId]);

  async function run(action: () => Promise<CustomPlanEditorV2>) {
    setBusy(true);
    setError(null);
    try {
      setPlan(await action());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  }

  async function openAdd() {
    try {
      const [mine, system] = await Promise.all([listWorkouts(initDataRaw), listSystemWorkouts(initDataRaw)]);
      const present = new Set(plan?.workouts.map((w) => w.workout_id));
      setAdding([...mine, ...system].filter((w) => !present.has(w.id)));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  if (plan === null) {
    return (
      <div data-testid="plan-editor-screen">
        <p className="plan-title">План</p>
        {error !== null ? <p className="gap-banner">{error}</p> : <p className="block-subtitle">Загружаю…</p>}
        <Button size="m" mode="outline" onClick={onBack}>Назад</Button>
      </div>
    );
  }

  const planWeeks = plan.weeks;
  const lastIndex = planWeeks.length;

  function deleteSummary(week: EditorWeekV2): string {
    const names = plan!.workouts
      .filter((w) => (week.quantities[String(w.workout_id)] ?? 0) > 0)
      .map((w) => `${w.title} ×${week.quantities[String(w.workout_id)]}`);
    return names.length === 0
      ? "В этой неделе нет занятий."
      : `Будет убрано занятий: ${week.total} (${names.join(", ")}).`;
  }

  return (
    <div data-testid="plan-editor-screen">
      <p className="plan-title">{plan.display_name}</p>
      <p className="block-subtitle">Сколько раз в неделю делать каждую тренировку. Дни выбираются отдельно, в расписании недели.</p>
      {plan.notice !== null && <p className="block-subtitle" data-testid="plan-editor-notice">{plan.notice}</p>}
      {error !== null && <p className="gap-banner" data-testid="plan-editor-error">{error}</p>}

      <Section className="block-section" header="Тренировки в плане">
<div className="plan-section-body">
        {plan.workouts.map((workout) => (
          <div key={workout.workout_id} className="plans-row-main">
            <span className="plans-row-title">{workout.title}</span>
            <Button
              size="s" mode="outline" data-testid={`editor-remove-workout-${workout.workout_id}`} disabled={busy || plan.workouts.length <= 1}
              onClick={() => setConfirm({ kind: "remove-workout", workoutId: workout.workout_id, title: workout.title })}
            >
              Убрать
            </Button>
          </div>
        ))}
        <Button size="s" mode="outline" data-testid="editor-add-workout" disabled={busy} onClick={() => void openAdd()}>
          + Добавить тренировку
        </Button>
      </div>
</Section>

      {planWeeks.map((week) => {
        const note = weekEmptyNote(week.total);
        const past = week.state === "past";
        return (
          <Section
            key={week.index} className={past ? "block-section plans-week-card plan-week-past" : "block-section plans-week-card"}
          >
<div className="plan-section-body">
            <div className="editor-week-head" data-testid={`editor-week-${week.index}`} data-state={week.state}>
              <div className="editor-week-head-main">
                <span>{`Неделя ${week.index} · ${weekRangeLabel(week.start_date)}`}</span>
                <button
                  type="button" className="plan-week-chip" data-testid={`editor-phase-${week.index}`}
                  disabled={busy || past} onClick={() => void run(() => setWeekPhase(initDataRaw, planId, week.index, nextPhase(week.phase)))}
                >
                  {PHASE_LABELS[week.phase]}
                </button>
                {past && <span className="block-subtitle">Прошла</span>}
              </div>
              <span className="plans-row-chip" data-testid={`editor-total-${week.index}`}>{`Всего ${week.total}`}</span>
            </div>
            {plan.workouts.map((workout) => {
              const bounds = quantityBounds(week, workout.workout_id);
              const value = week.quantities[String(workout.workout_id)] ?? 0;
              const key = `${week.index}-${workout.workout_id}`;
              const change = (delta: number) => void run(() => setWeekQuantities(
                initDataRaw, planId, week.index, { [String(workout.workout_id)]: value + delta },
              ));
              return (
                <div key={key} className="plans-row-main editor-qty-row">
                  <span className="plans-row-title">{workout.title}</span>
                  <Button size="s" mode="outline" aria-label={`Меньше: ${workout.title}, неделя ${week.index}`}
                    data-testid={`editor-dec-${key}`} disabled={busy || !bounds.canDec} onClick={() => change(-1)}>−</Button>
                  <span className="plans-row-chip" data-testid={`editor-qty-${key}`}>{value}</span>
                  <Button size="s" mode="outline" aria-label={`Больше: ${workout.title}, неделя ${week.index}`}
                    data-testid={`editor-inc-${key}`} disabled={busy || !bounds.canInc} onClick={() => change(1)}>+</Button>
                </div>
              );
            })}
            {note !== null && <p className="block-subtitle" data-testid={`editor-rest-note-${week.index}`}>{note}</p>}
            <div className="plans-confirm-actions">
              {!past && (
                <Button size="s" mode="outline" data-testid={`editor-schedule-${week.index}`} onClick={() => onOpenSchedule(week.index)}>
                  Расписание
                </Button>
              )}
              <Button size="s" mode="outline" data-testid={`editor-insert-${week.index}`} disabled={busy || lastIndex >= 52}
                onClick={() => void run(() => insertPlanWeek(initDataRaw, planId, week.index))}>
                + Неделя после
              </Button>
              {week.state === "future" && (
                <Button size="s" mode="outline" data-testid={`editor-delete-${week.index}`} disabled={busy || lastIndex <= 1}
                  onClick={() => setConfirm({ kind: "delete-week", index: week.index })}>
                  Удалить неделю
                </Button>
              )}
            </div>
          </div>
</Section>
        );
      })}

      <Button size="l" mode="outline" stretched onClick={close}>Готово</Button>

      {confirm !== null && (
        <FormSheet title="Подтверждение" onClose={() => setConfirm(null)}>
          <div data-testid="editor-confirm">
            {confirm.kind === "delete-week" ? (
              <>
                <p className="plan-title">{`Удалить неделю ${confirm.index}?`}</p>
                <p className="block-subtitle">{deleteSummary(planWeeks[confirm.index - 1])} Следующие недели сдвинутся на неделю назад.</p>
              </>
            ) : (
              <>
                <p className="plan-title">{`Убрать «${confirm.title}» из плана?`}</p>
                <p className="block-subtitle">Невыполненные занятия в текущей и будущих неделях будут убраны. Выполненные и история остаются.</p>
              </>
            )}
            <div className="plans-confirm-actions">
              <Button size="m" data-testid="editor-confirm-ok" disabled={busy}
                onClick={() => void run(() => confirm.kind === "delete-week"
                  ? deletePlanWeek(initDataRaw, planId, confirm.index)
                  : removePlanWorkout(initDataRaw, planId, confirm.workoutId))}>
                {confirm.kind === "delete-week" ? "Удалить" : "Убрать"}
              </Button>
              <Button size="m" mode="outline" data-testid="editor-confirm-cancel" disabled={busy} onClick={() => setConfirm(null)}>
                Отмена
              </Button>
            </div>
          </div>
        </FormSheet>
      )}

      {adding !== null && (
        <FormSheet title="Добавить тренировку" onClose={() => setAdding(null)}>
          <p className="plan-title">Добавить тренировку</p>
          {adding.length === 0 && <p className="block-subtitle">Все ваши тренировки уже в плане.</p>}
          {adding.map((workout) => (
            <button
              key={workout.id} type="button" className="program-card-button plan-exercise-option"
              data-testid={`editor-add-pick-${workout.id}`}
              onClick={() => { setAdding(null); void run(() => addPlanWorkout(initDataRaw, planId, workout.id)); }}
            >
              {workout.title}
            </button>
          ))}
          <Button size="m" mode="outline" onClick={() => setAdding(null)}>Отмена</Button>
        </FormSheet>
      )}
    </div>
  );
}
