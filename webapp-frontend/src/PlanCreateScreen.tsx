import { Button, Section } from "@telegram-apps/telegram-ui";
import { useCallback, useEffect, useState } from "react";

import {
  createCustomPlan, listCustomPlans, listSystemWorkouts, listWorkouts, type PlanPhaseV2, type WorkoutResponseV2,
} from "./apiV2";
import { FormSheet } from "./FormSheet";
import { PHASE_LABELS, WEEK_MAX_TOTAL, nextPhase, weekEmptyNote } from "./planEditorMath";
import { useBackButton } from "./useBackButton";

// UX-EDITOR — создание своего плана по неделям: 1) название, начало, длина, тренировки; 2) количество каждой
// тренировки по неделям и фазы (та же матрица, что в редакторе); «Создать план» → редактор созданного плана.
// Если уже есть активный свой план — сначала подтверждение замены (лист в странице, не window.confirm):
// остановка старого и создание нового идут одним запросом на сервере (replace_custom_plan_id).

type Props = {
  initDataRaw: string;
  /** Номер текущей календарной недели плана (для «С этой недели» / «Со следующей»). */
  currentWeekNumber: number | null;
  onBack: () => void;
  onCreated: (planId: number) => void;
};

export function PlanCreateScreen({ initDataRaw, currentWeekNumber, onBack, onCreated }: Props) {
  const [workouts, setWorkouts] = useState<WorkoutResponseV2[] | null>(null);
  const [step, setStep] = useState<"form" | "matrix">("form");
  const [name, setName] = useState("Мой план");
  const [startNext, setStartNext] = useState(false);
  const [weekCount, setWeekCount] = useState(4);
  const [selected, setSelected] = useState<number[]>([]);
  const [quantities, setQuantities] = useState<Record<number, number[]>>({});
  const [phases, setPhases] = useState<PlanPhaseV2[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmReplace, setConfirmReplace] = useState(false);
  // Активный план читаем сами, а не берём из состояния «Планов»: тот мог ещё не загрузиться (быстрый тап) —
  // тогда новый план создался бы рядом со старым без вопроса о замене. До ответа «Создать план» недоступна.
  const [replacing, setReplacing] = useState<{ id: number; name: string } | null | undefined>(undefined);

  const goBack = useCallback(() => {
    if (saving) {
      return;
    }
    if (confirmReplace) {
      setConfirmReplace(false);
    } else if (step === "matrix") {
      setStep("form");
    } else {
      onBack();
    }
  }, [saving, confirmReplace, step, onBack]);
  useBackButton(goBack, [goBack], true, false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listWorkouts(initDataRaw), listSystemWorkouts(initDataRaw)])
      .then(([mine, system]) => { if (!cancelled) { setWorkouts([...mine, ...system]); } })
      .catch((reason) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : String(reason));
          setWorkouts([]);
        }
      });
    return () => { cancelled = true; };
  }, [initDataRaw]);

  useEffect(() => {
    let cancelled = false;
    listCustomPlans(initDataRaw)
      .then((plans) => {
        if (!cancelled) {
          const active = plans.find((plan) => plan.is_active);
          setReplacing(active === undefined ? null : { id: active.id, name: active.display_name });
        }
      })
      .catch((reason) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      });
    return () => { cancelled = true; };
  }, [initDataRaw]);

  function toMatrix() {
    // Старт: по одному занятию каждой тренировки в неделю; фазы — «База».
    const next: Record<number, number[]> = {};
    for (const id of selected) {
      next[id] = Array.from({ length: weekCount }, (_, week) => quantities[id]?.[week] ?? 1);
    }
    setQuantities(next);
    setPhases(Array.from({ length: weekCount }, (_, week) => phases[week] ?? "base"));
    setStep("matrix");
  }

  const total = (week: number) => selected.reduce((sum, id) => sum + (quantities[id]?.[week] ?? 0), 0);
  const anyLesson = Array.from({ length: weekCount }, (_, week) => total(week)).some((count) => count > 0);

  function change(id: number, week: number, delta: number) {
    setQuantities((prev) => {
      const row = [...(prev[id] ?? [])];
      row[week] = Math.max(0, (row[week] ?? 0) + delta);
      return { ...prev, [id]: row };
    });
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const created = await createCustomPlan(initDataRaw, {
        display_name: name.trim() || "Мой план",
        workout_ids: selected,
        quantities: selected.map((id) => quantities[id]),
        phases,
        start_week_number: currentWeekNumber === null ? null : currentWeekNumber + (startNext ? 1 : 0),
        ...(replacing ? { replace_custom_plan_id: replacing.id } : {}),
      });
      onCreated(created.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setSaving(false);
      setConfirmReplace(false);
    }
  }

  const title = (id: number) => workouts?.find((w) => w.id === id)?.title ?? "Тренировка";

  return (
    <div data-testid="plan-create-screen" className="plan-form">
      <p className="plan-title">Новый план по неделям</p>
      {step === "form" && (
        <>
          <Section className="block-section" header="Название">
<div className="plan-section-body">
            <input
              className="ux-text-input" value={name} maxLength={255} aria-label="Название плана"
              data-testid="plan-create-name" onChange={(event) => setName(event.target.value)}
            />
          </div>
</Section>
          <Section className="block-section" header="Начало">
<div className="plan-section-body">
            <div className="plans-confirm-actions">
              <Button size="s" mode={startNext ? "outline" : "filled"} data-testid="plan-create-start-now"
                onClick={() => setStartNext(false)}>С этой недели</Button>
              <Button size="s" mode={startNext ? "filled" : "outline"} data-testid="plan-create-start-next"
                onClick={() => setStartNext(true)}>Со следующей</Button>
            </div>
          </div>
</Section>
          <Section className="block-section" header="Недель в плане">
<div className="plan-section-body">
            <div className="editor-qty-row">
              <Button size="s" mode="outline" aria-label="Меньше недель" disabled={weekCount <= 1}
                onClick={() => setWeekCount((n) => n - 1)}>−</Button>
              <span className="plans-row-chip" data-testid="plan-create-weeks">{weekCount}</span>
              <Button size="s" mode="outline" aria-label="Больше недель" disabled={weekCount >= 52}
                onClick={() => setWeekCount((n) => n + 1)}>+</Button>
            </div>
          </div>
</Section>
          <Section className="block-section" header="Тренировки">
<div className="plan-section-body">
            {workouts === null && <p className="block-subtitle">Загружаю…</p>}
            {workouts?.length === 0 && <p className="block-subtitle">Нет доступных тренировок. Соберите свою в «Мои тренировки».</p>}
            {workouts?.map((workout) => (
              <label key={workout.id} className="plans-row-main plan-form-check">
                <input
                  type="checkbox" checked={selected.includes(workout.id)} data-testid={`plan-create-workout-${workout.id}`}
                  onChange={(event) => setSelected((prev) => event.target.checked
                    ? [...prev, workout.id] : prev.filter((id) => id !== workout.id))}
                />
                <span className="plans-row-title">{workout.title}</span>
              </label>
            ))}
          </div>
</Section>
        </>
      )}
      {step === "matrix" && (
        <>
          <p className="block-subtitle">Сколько раз в неделю делать каждую тренировку. Дни выберете после создания, в расписании недели.</p>
          {Array.from({ length: weekCount }, (_, week) => {
            const note = weekEmptyNote(total(week));
            return (
              <Section key={week} className="block-section plans-week-card">
<div className="plan-section-body">
                <div className="editor-week-head" data-testid={`create-week-${week + 1}`}>
                  <div className="editor-week-head-main">
                    <span>{`Неделя ${week + 1}`}</span>
                    <button type="button" className="plan-week-chip" data-testid={`create-phase-${week + 1}`}
                      onClick={() => setPhases((prev) => prev.map((p, i) => (i === week ? nextPhase(p) : p)))}>
                      {PHASE_LABELS[phases[week] ?? "base"]}
                    </button>
                  </div>
                  <span className="plans-row-chip" data-testid={`create-total-${week + 1}`}>{`Всего ${total(week)}`}</span>
                </div>
                {selected.map((id) => (
                  <div key={id} className="plans-row-main editor-qty-row">
                    <span className="plans-row-title">{title(id)}</span>
                    <Button size="s" mode="outline" aria-label={`Меньше: ${title(id)}, неделя ${week + 1}`}
                      data-testid={`create-dec-${week + 1}-${id}`} disabled={(quantities[id]?.[week] ?? 0) <= 0}
                      onClick={() => change(id, week, -1)}>−</Button>
                    <span className="plans-row-chip" data-testid={`create-qty-${week + 1}-${id}`}>{quantities[id]?.[week] ?? 0}</span>
                    <Button size="s" mode="outline" aria-label={`Больше: ${title(id)}, неделя ${week + 1}`}
                      data-testid={`create-inc-${week + 1}-${id}`} disabled={total(week) >= WEEK_MAX_TOTAL}
                      onClick={() => change(id, week, 1)}>+</Button>
                  </div>
                ))}
                {note !== null && <p className="block-subtitle">{note}</p>}
              </div>
</Section>
            );
          })}
        </>
      )}
      {error !== null && <p className="gap-banner" data-testid="plan-create-error">{error}</p>}
      <div className="plan-form-actions">
        {step === "form" ? (
          <Button className="action-button vs-primary" size="l" stretched data-testid="plan-create-next"
            disabled={selected.length === 0 || name.trim() === ""} onClick={toMatrix}>
            Далее
          </Button>
        ) : (
          <Button className="action-button vs-primary" size="l" stretched data-testid="plan-create-save"
            disabled={saving || !anyLesson || replacing === undefined}
            onClick={() => (replacing ? setConfirmReplace(true) : void save())}>
            {saving ? "Создаю…" : "Создать план"}
          </Button>
        )}
        <Button className="action-button" size="l" mode="outline" stretched data-testid="plan-create-cancel"
          disabled={saving} onClick={step === "matrix" ? () => setStep("form") : onBack}>
          {step === "matrix" ? "Назад" : "Отмена"}
        </Button>
      </div>

      {confirmReplace && replacing && (
        <FormSheet title="Заменить план" onClose={() => { if (!saving) { setConfirmReplace(false); } }}>
          <div data-testid="plan-replace-confirm">
            <p className="plan-title">Заменить план?</p>
            <p className="block-subtitle">
              {`У вас уже есть план «${replacing.name}». Новый заменит его: будущие занятия «${replacing.name}» будут сняты, история сохранится.`}
            </p>
            <div className="plans-confirm-actions">
              <Button size="m" data-testid="plan-replace-ok" disabled={saving} onClick={() => void save()}>
                {saving ? "Заменяю…" : "Заменить"}
              </Button>
              <Button size="m" mode="outline" data-testid="plan-replace-cancel" disabled={saving}
                onClick={() => setConfirmReplace(false)}>Отмена</Button>
            </div>
          </div>
        </FormSheet>
      )}
    </div>
  );
}
