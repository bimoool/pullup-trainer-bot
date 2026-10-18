import { Button, Section } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { createCustomPlan, listSystemWorkouts, listWorkouts, type WorkoutResponseV2 } from "./apiV2";
import { useBackButton } from "./useBackButton";

// issue #304 (PROGRAM_PLAN_V2 §7) — минимальный экран «Свой план»: ротация тренировок + ИСТИННЫЙ
// объём по неделям задаётся в редакторе (PlanEditorScreen, UX-EDITOR), здесь — состав и длина плана.

type Props = {
  initDataRaw: string;
  onBack: () => void;
  onCreated: (planId: number) => void;
};

export function CustomPlanScreen({ initDataRaw, onBack, onCreated }: Props) {
  const [workouts, setWorkouts] = useState<WorkoutResponseV2[] | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [name, setName] = useState("Свой план");
  const [weekCount, setWeekCount] = useState(4);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useBackButton(onBack, [onBack], true, false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listWorkouts(initDataRaw), listSystemWorkouts(initDataRaw)])
      .then(([mine, system]) => {
        if (!cancelled) {
          setWorkouts([...mine, ...system]);
        }
      })
      .catch((reason) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : String(reason));
          setWorkouts([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  async function handleSave() {
    if (selected.length === 0) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      // Старт: по одному занятию каждой тренировки в неделю; точные количества и фазы — в редакторе.
      const created = await createCustomPlan(initDataRaw, {
        display_name: name.trim() || "Свой план",
        workout_ids: selected,
        quantities: selected.map(() => Array.from({ length: weekCount }, () => 1)),
      });
      onCreated(created.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setSaving(false);
    }
  }

  return (
    <div data-testid="custom-plan-screen">
      <p className="plan-title">Свой план</p>
      <Section className="block-section" header="Название">
        <input
          className="text-input" value={name} maxLength={255} aria-label="Название плана"
          onChange={(event) => setName(event.target.value)}
        />
      </Section>
      <Section className="block-section" header="Тренировки (по очереди)">
        {workouts === null && <p className="block-subtitle">Загружаю…</p>}
        {workouts?.map((workout) => (
          <label key={workout.id} className="plans-row-main">
            <input
              type="checkbox" checked={selected.includes(workout.id)}
              onChange={(event) => setSelected((prev) => event.target.checked
                ? [...prev, workout.id] : prev.filter((id) => id !== workout.id))}
            />
            <span className="plans-row-title">{workout.title}</span>
          </label>
        ))}
      </Section>
      <Section className="block-section" header="Недель в плане">
        <div className="plans-row-main editor-qty-row">
          <Button size="s" mode="outline" aria-label="Меньше недель" disabled={weekCount <= 1}
            onClick={() => setWeekCount((n) => n - 1)}>−</Button>
          <span className="plans-row-chip" data-testid="custom-plan-weeks">{weekCount}</span>
          <Button size="s" mode="outline" aria-label="Больше недель" disabled={weekCount >= 52}
            onClick={() => setWeekCount((n) => n + 1)}>+</Button>
        </div>
        <p className="block-subtitle">Сначала по одному занятию каждой тренировки в неделю — дальше настроите по неделям.</p>
      </Section>
      {error !== null && <p className="gap-banner">{error}</p>}
      <div className="pre-transport">
        <Button
          className="action-button vs-primary" size="l" stretched data-testid="custom-plan-save"
          disabled={saving || selected.length === 0} onClick={() => void handleSave()}
        >
          {saving ? "Сохраняю…" : "Создать план"}
        </Button>
        <Button className="action-button" size="l" mode="outline" stretched onClick={onBack}>
          Отмена
        </Button>
      </div>
    </div>
  );
}
