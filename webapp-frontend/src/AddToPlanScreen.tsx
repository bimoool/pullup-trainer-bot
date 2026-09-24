import { Button, Spinner } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { createPlanItem, fetchPlan } from "./apiV2";
import { DayPicker } from "./DayPicker";
import { useBackButton } from "./useBackButton";

type Props = {
  initDataRaw: string;
  workoutId: number;
  workoutTitle: string;
  onBack: () => void;
  /** Вызывается после успешного добавления — caller закрывает весь
   * Builder-стек и возвращается на «Планы» (issue #188, раздел 5 — "не
   * вернуться в My Workouts/Editor, а именно на Планы"). */
  onSuccess: () => void;
};

type LoadState =
  | { phase: "loading" }
  | { phase: "ready"; planWeekId: number | null }
  | { phase: "error"; message: string };

/**
 * Phase C5a/C5b/D3 (issue #188) — минимальный Add to Plan flow поверх уже
 * существующего PlanItem API (createPlanItem, тот же паттерн, что
 * DashboardScreen.tsx's "+ Добавить упражнение" уже использует —
 * count_per_week: 1, plan_week_id = текущая неделя, day_of_week = выбор
 * пользователя или null для свободного пула). Не создаёт новую
 * календарную модель, не пишет отдельный PlanItem-эндпоинт.
 *
 * Отправляется ТОЛЬКО complex_id, без exercise_id (C5b QA-fix) —
 * PlanItemCreateRequest._exactly_one_target (app/web/schemas_v2.py)
 * требует ровно одно из exercise_id/complex_id, оба вместе дают 422.
 * PlanItem.exercise_id — NOT NULL на уровне БД, но это уже решено на
 * backend-стороне (TrainingPlanRepository.create_plan_item резолвит
 * placeholder из первого ComplexItem выбранного Workout, если
 * exercise_id не передан) — frontend не должен знать/дублировать эту
 * деталь.
 *
 * DayPicker (D3) — вынесен в отдельный компонент, переиспользуется
 * MovePlanItemScreen.tsx, разметка/стили не изменены.
 */
export function AddToPlanScreen({ initDataRaw, workoutId, workoutTitle, onBack, onSuccess }: Props) {
  const [loadState, setLoadState] = useState<LoadState>({ phase: "loading" });
  const [selectedDay, setSelectedDay] = useState<number | "free_pool" | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchPlan(initDataRaw)
      .then((plan) => {
        if (cancelled) {
          return;
        }
        // Та же логика "текущая неделя", что DashboardScreen.tsx уже
        // использует (currentWeekId) — последняя запись в weeks.
        const currentWeekId = plan !== null && plan.plan_weeks.length > 0
          ? plan.plan_weeks[plan.plan_weeks.length - 1].id
          : null;
        setLoadState({ phase: "ready", planWeekId: currentWeekId });
      })
      .catch((error) => {
        if (!cancelled) {
          setLoadState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  useBackButton(onBack, [onBack]);

  async function handleSubmit() {
    if (loadState.phase !== "ready" || selectedDay === null || submitting) {
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      await createPlanItem(initDataRaw, {
        complex_id: workoutId,
        plan_week_id: loadState.planWeekId,
        day_of_week: selectedDay === "free_pool" ? null : selectedDay,
        count_per_week: 1,
      });
      onSuccess();
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : String(error));
      setSubmitting(false);
    }
  }

  if (loadState.phase === "loading") {
    return <Spinner size="m" />;
  }
  if (loadState.phase === "error") {
    return <p className="gap-banner">Не удалось загрузить: {loadState.message}</p>;
  }

  return (
    <div>
      <p className="plan-title">Добавить в план</p>
      <p className="block-subtitle">{workoutTitle}</p>

      <DayPicker selectedDay={selectedDay} onSelect={setSelectedDay} />

      {submitError && <p className="gap-banner">Не удалось добавить: {submitError}</p>}

      <Button
        className="action-button" size="l" stretched
        disabled={selectedDay === null || submitting}
        onClick={() => void handleSubmit()}
      >
        {submitting ? <Spinner size="s" /> : "Добавить"}
      </Button>
    </div>
  );
}
