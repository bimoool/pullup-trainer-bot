import { Button, Section } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { createCustomPlan, listSystemWorkouts, listWorkouts, type WorkoutResponseV2 } from "./apiV2";
import { parseWeekVolumes } from "./customPlanFormat";
import { useBackButton } from "./useBackButton";

// issue #304 (PROGRAM_PLAN_V2 §7) — минимальный экран «Свой план»: ротация тренировок + ИСТИННЫЙ
// объём по неделям («2 2 0 2 2 0» — 0 = пустая неделя), необязательные дни недели — подсказка
// размещения, не объём. Полировка редактора — отдельная задача (P2).

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

type Props = {
  initDataRaw: string;
  onBack: () => void;
  onCreated: () => void;
};

export function CustomPlanScreen({ initDataRaw, onBack, onCreated }: Props) {
  const [workouts, setWorkouts] = useState<WorkoutResponseV2[] | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [name, setName] = useState("Свой план");
  const [weeksText, setWeeksText] = useState("2 2 0 2 2 0");
  const [weekdays, setWeekdays] = useState<number[]>([]);
  const [cycle, setCycle] = useState(false);
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

  const parsed = parseWeekVolumes(weeksText);

  async function handleSave() {
    if (parsed.error !== null || selected.length === 0) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createCustomPlan(initDataRaw, {
        display_name: name.trim() || "Свой план",
        workout_ids: selected,
        weeks: parsed.weeks,
        repeat: cycle ? "cycle" : "once",
        preferred_weekdays: weekdays.length > 0 ? [...weekdays].sort((a, b) => a - b) : null,
      });
      onCreated();
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
      <Section className="block-section" header="Тренировок по неделям">
        <input
          className="text-input" value={weeksText} aria-label="Тренировок по неделям" data-testid="custom-plan-weeks"
          onChange={(event) => setWeeksText(event.target.value)}
        />
        <p className="block-subtitle" data-testid="custom-plan-weeks-preview">
          {parsed.error ?? parsed.weeks.map((count, index) => `Н${index + 1}: ${count}`).join(" · ")}
        </p>
        <label className="plans-row-main">
          <input type="checkbox" checked={cycle} onChange={(event) => setCycle(event.target.checked)} />
          <span className="block-subtitle">Повторять по кругу</span>
        </label>
      </Section>
      <Section className="block-section" header="Дни недели (подсказка, не обязательно)">
        <div className="plans-confirm-actions">
          {WEEKDAYS.map((label, index) => (
            <Button
              key={label} size="s" mode={weekdays.includes(index) ? "filled" : "outline"}
              onClick={() => setWeekdays((prev) => prev.includes(index) ? prev.filter((d) => d !== index) : [...prev, index])}
            >
              {label}
            </Button>
          ))}
        </div>
      </Section>
      {error !== null && <p className="gap-banner">{error}</p>}
      <div className="pre-transport">
        <Button
          className="action-button vs-primary" size="l" stretched data-testid="custom-plan-save"
          disabled={saving || parsed.error !== null || selected.length === 0} onClick={() => void handleSave()}
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
