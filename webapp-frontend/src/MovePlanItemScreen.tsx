import { Button, Spinner } from "@telegram-apps/telegram-ui";
import { useState } from "react";

import { movePlanItem } from "./apiV2";
import { DayPicker } from "./DayPicker";
import { useBackButton } from "./useBackButton";

type Props = {
  initDataRaw: string;
  planItemId: number;
  title: string;
  /** Текущий день PlanItem — предзаполняется в DayPicker (issue #188,
   * раздел 6 — "текущий day preselected"). null = свободный пул. */
  currentDayOfWeek: number | null;
  onBack: () => void;
  onSuccess: () => void;
};

/**
 * Phase D3 (issue #188) — «Перенести» на карточке Планов. Тот же
 * DayPicker, что AddToPlanScreen.tsx уже использует (вынесен в
 * DayPicker.tsx), под уже существующий D2 API (PATCH /plan-items/{id}).
 * plan_week_id не меняется в этой волне — PlanItem остаётся в той же
 * current PlanWeek (по заданию).
 */
export function MovePlanItemScreen({ initDataRaw, planItemId, title, currentDayOfWeek, onBack, onSuccess }: Props) {
  const [selectedDay, setSelectedDay] = useState<number | "free_pool" | null>(
    currentDayOfWeek === null ? "free_pool" : currentDayOfWeek,
  );
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useBackButton(onBack, [onBack]);

  async function handleSubmit() {
    if (selectedDay === null || submitting) {
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      await movePlanItem(initDataRaw, planItemId, selectedDay === "free_pool" ? null : selectedDay);
      onSuccess();
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : String(error));
      setSubmitting(false);
    }
  }

  return (
    <div>
      <p className="plan-title">Перенести</p>
      <p className="block-subtitle">{title}</p>

      <DayPicker selectedDay={selectedDay} onSelect={setSelectedDay} />

      {submitError && <p className="gap-banner">Не удалось перенести: {submitError}</p>}

      <Button
        className="action-button" size="l" stretched
        disabled={selectedDay === null || submitting}
        onClick={() => void handleSubmit()}
      >
        {submitting ? <Spinner size="s" /> : "Сохранить"}
      </Button>
    </div>
  );
}
