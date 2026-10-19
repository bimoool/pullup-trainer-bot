import { Button, Section } from "@telegram-apps/telegram-ui";
import { useCallback, useEffect, useState } from "react";

import { fetchWeekSchedule, placeOnDay, type WeekScheduleV2 } from "./apiV2";
import { FormSheet } from "./FormSheet";
import { DAY_LABELS } from "./DayPicker";
import { remainingLabel } from "./planEditorMath";
import { weekRangeLabel } from "./planWeekNav";
import { useBackButton } from "./useBackButton";

// UX-EDITOR (UX-25): расписание недели — для каждой тренировки «осталось разместить N», семь дней с явным
// −/+ (не тап-циклом), итог по дню; одну тренировку можно поставить в один день несколько раз. Прошедшие дни
// недоступны; когда всё размещено — «все занятия размещены» (а не молчаливое игнорирование).

type Props = { initDataRaw: string; planId: number; index: number; onBack: () => void };

export function WeekScheduleScreen({ initDataRaw, planId, index, onBack }: Props) {
  const [view, setView] = useState<WeekScheduleV2 | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmUnplace, setConfirmUnplace] = useState<{ workoutId: number; title: string; day: number } | null>(null);

  const close = useCallback(() => { if (!busy) { onBack(); } }, [busy, onBack]);
  useBackButton(close, [close], true, false);

  useEffect(() => {
    let cancelled = false;
    fetchWeekSchedule(initDataRaw, planId, index)
      .then((data) => { if (!cancelled) { setView(data); } })
      .catch((reason) => { if (!cancelled) { setError(reason instanceof Error ? reason.message : String(reason)); } });
    return () => { cancelled = true; };
  }, [initDataRaw, planId, index]);

  async function act(workoutId: number, day: number, unplace: boolean) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setView(await placeOnDay(initDataRaw, planId, index, workoutId, day, unplace));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
      setConfirmUnplace(null);
    }
  }

  if (view === null) {
    return (
      <div data-testid="week-schedule-screen">
        <p className="plan-title">Расписание недели</p>
        {error !== null ? <p className="gap-banner">{error}</p> : <p className="block-subtitle">Загружаю…</p>}
        <Button size="m" mode="outline" onClick={onBack}>Назад</Button>
      </div>
    );
  }

  return (
    <div data-testid="week-schedule-screen">
      <p className="plan-title">{`Неделя ${index} · ${weekRangeLabel(view.start_date)}`}</p>
      <p className="block-subtitle">Для каждой тренировки выберите день. Одну тренировку можно поставить в один день несколько раз.</p>
      {error !== null && <p className="gap-banner" data-testid="schedule-error">{error}</p>}
      {notice !== null && <p className="block-subtitle" data-testid="schedule-notice">{notice}</p>}

      <Section className="block-section" header="Всего занятий в день">
<div className="plan-section-body">
        <div className="schedule-day-totals">
          {view.days.map((day) => (
            <span key={day.day} className="plans-row-chip" data-testid={`schedule-day-total-${day.day}`} data-state={day.state}>
              {`${DAY_LABELS[day.day].label} ${day.total}`}
            </span>
          ))}
        </div>
      </div>
</Section>

      {view.workouts.length === 0 && <p className="block-subtitle">В этой неделе нет занятий.</p>}
      {view.workouts.map((workout) => {
        const exhausted = workout.remaining === 0;
        return (
          <Section key={workout.workout_id} className="block-section" header={workout.title}>
<div className="plan-section-body">
            <p className="block-subtitle" data-testid={`schedule-remaining-${workout.workout_id}`}>
              {workout.quantity === 0 ? "В этой неделе не запланировано" : remainingLabel(workout.remaining)}
            </p>
            {workout.items.some((item) => item.missed) && (
              <p className="block-subtitle" data-testid={`schedule-missed-${workout.workout_id}`}>
                {`пропущено: ${workout.items.filter((item) => item.missed).length}`}
              </p>
            )}
            {view.days.map((day) => {
              const count = workout.placed_by_day[day.day] ?? 0;
              const past = day.state === "past";
              return (
                <div key={day.day} className="plans-row-main editor-qty-row">
                  <span className="plans-row-title">{DAY_LABELS[day.day].label}{count > 1 ? ` ×${count}` : ""}</span>
                  <Button size="s" mode="outline" aria-label={`Убрать: ${workout.title}, ${DAY_LABELS[day.day].label}`}
                    data-testid={`schedule-dec-${workout.workout_id}-${day.day}`} disabled={busy || count === 0}
                    onClick={() => setConfirmUnplace({ workoutId: workout.workout_id, title: workout.title, day: day.day })}>−</Button>
                  <span className="plans-row-chip" data-testid={`schedule-count-${workout.workout_id}-${day.day}`}>{count}</span>
                  <Button size="s" mode="outline" aria-label={`Поставить: ${workout.title}, ${DAY_LABELS[day.day].label}`}
                    data-testid={`schedule-inc-${workout.workout_id}-${day.day}`} disabled={busy || past}
                    onClick={() => {
                      if (exhausted) {
                        setNotice("Все занятия размещены");
                        return;
                      }
                      void act(workout.workout_id, day.day, false);
                    }}>+</Button>
                  {past && <span className="block-subtitle">прошёл</span>}
                </div>
              );
            })}
          </div>
</Section>
        );
      })}

      <Button size="l" mode="outline" stretched onClick={close}>Готово</Button>

      {confirmUnplace !== null && (
        <FormSheet title="Подтверждение" onClose={() => setConfirmUnplace(null)}>
          <div data-testid="schedule-confirm">
            <p className="plan-title">{`Снять «${confirmUnplace.title}» с дня ${DAY_LABELS[confirmUnplace.day].label}?`}</p>
            <p className="block-subtitle">Занятие останется в неделе без дня — его можно поставить на другой день.</p>
            <div className="plans-confirm-actions">
              <Button size="m" data-testid="schedule-confirm-ok" disabled={busy}
                onClick={() => void act(confirmUnplace.workoutId, confirmUnplace.day, true)}>Снять</Button>
              <Button size="m" mode="outline" data-testid="schedule-confirm-cancel" disabled={busy}
                onClick={() => setConfirmUnplace(null)}>Отмена</Button>
            </div>
          </div>
        </FormSheet>
      )}
    </div>
  );
}
