import { Button, Textarea } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  fetchBackdatePlan,
  submitBackdate,
  type BackdateSubmitRequest,
  type WorkoutPlanResponse,
  type WorkoutSubmitResponse,
} from "./api";
import { AnomalyLines, BlockForm, parseOptionalWeight, parseSetValue, parseSetValues, replaceAt } from "./BlockForm";

type Props = {
  initDataRaw: string;
  onCancel: () => void;
  onSaved: () => void;
};

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "not_ready"; status: string }
  | { phase: "form"; plan: WorkoutPlanResponse }
  | { phase: "anomaly_confirm"; plan: WorkoutPlanResponse; body: BackdateSubmitRequest; result: WorkoutSubmitResponse };

// Тот же смысл, что STATUS_MESSAGES в WorkoutScreen.tsx, но для статусов
// _resolve_backdate_context (app/web/routes.py) — там нет readiness-гейтов
// (too_early/gap_retest_required/deload_due/equipment_setup_required), но
// есть свой статус "future_date".
const STATUS_MESSAGES: Record<string, string> = {
  no_access: "Нет активной подписки. Оформи её в боте, потом возвращайся сюда.",
  no_active_set: "Нужен хотя бы один замер, чтобы вносить тренировки задним числом — начни его в боте.",
  not_onboarded: "Похоже, ты ещё не проходил онбординг — начни его в боте.",
  future_date: "Эта дата ещё не наступила — бэкдейт работает только для прошлого.",
};

const TODAY = new Date().toISOString().slice(0, 10);

/** "Добавить за дату" (issue #52, волна 2) — упрощённый для веба аналог
 * календаря бота (app/bot/handlers/backdate.py): обычный <input type="date">
 * с max=сегодня вместо grid-календаря, единственная реальная проверка даты
 * в боте — "не в будущем" (см. докстринг submit_backdated_workout в
 * app/web/routes.py, лимита "не старше N дней" в боте на самом деле нет).
 * Снаряд наследуется из GET /api/workout/backdate/plan (resolve_next_targets)
 * — та же BlockForm/анти-аномальный поток, что и WorkoutScreen.tsx/
 * HistoryEditForm.tsx. */
export function BackdateForm({ initDataRaw, onCancel, onSaved }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
  const [performedAt, setPerformedAt] = useState(TODAY);
  const [blockAWorking, setBlockAWorking] = useState<string[]>([]);
  const [blockAMax, setBlockAMax] = useState("");
  const [blockBWorking, setBlockBWorking] = useState<string[]>([]);
  const [blockBMax, setBlockBMax] = useState("");
  const [blockAActualWeight, setBlockAActualWeight] = useState("");
  const [blockBActualWeight, setBlockBActualWeight] = useState("");
  const [blockABandItem, setBlockABandItem] = useState("");
  const [blockBBandItem, setBlockBBandItem] = useState("");
  const [comment, setComment] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const plan = await fetchBackdatePlan(initDataRaw);
        if (cancelled) {
          return;
        }
        if (plan.status === "ready") {
          setBlockAWorking(Array(plan.work_sets_a ?? 0).fill(""));
          setBlockBWorking(Array(plan.work_sets_b ?? 0).fill(""));
          setState({ phase: "form", plan });
        } else {
          setState({ phase: "not_ready", status: plan.status });
        }
      } catch (error) {
        if (!cancelled) {
          setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  async function handleSubmit(plan: WorkoutPlanResponse, confirmAnomalies: boolean) {
    if (!performedAt) {
      setFormError("Укажи дату тренировки.");
      return;
    }
    const workingA = parseSetValues(blockAWorking);
    const maxA = parseSetValue(blockAMax);
    const workingB = parseSetValues(blockBWorking);
    const maxB = parseSetValue(blockBMax);
    if (workingA === null || maxA === null || workingB === null || maxB === null) {
      setFormError("Заполни все подходы числами — пустые или нечисловые поля недопустимы.");
      return;
    }
    const actualWeightA = parseOptionalWeight(blockAActualWeight);
    const actualWeightB = parseOptionalWeight(blockBActualWeight);
    if (!actualWeightA.ok || !actualWeightB.ok) {
      setFormError("Фактический вес должен быть положительным числом, если он указан.");
      return;
    }
    setFormError(null);

    const body: BackdateSubmitRequest = {
      performed_at: performedAt,
      block_a_working_reps: workingA,
      block_a_max_reps: maxA,
      block_b_working_reps: workingB,
      block_b_max_reps: maxB,
      block_a_actual_weight: actualWeightA.value,
      block_b_actual_weight: actualWeightB.value,
      block_a_actual_band_item_id: blockABandItem ? Number(blockABandItem) : null,
      block_b_actual_band_item_id: blockBBandItem ? Number(blockBBandItem) : null,
      comment: comment.trim() || null,
      confirm_anomalies: confirmAnomalies,
    };

    setSubmitting(true);
    try {
      const result = await submitBackdate(initDataRaw, body);
      if (result.status === "anomaly_confirm_required") {
        setState({ phase: "anomaly_confirm", plan, body, result });
        return;
      }
      if (result.status !== "ok") {
        setFormError(STATUS_MESSAGES[result.status] ?? `Не удалось записать (статус: ${result.status}).`);
        return;
      }
      onSaved();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  }

  if (state.phase === "loading") {
    return <p className="screen-message">Загружаю форму…</p>;
  }
  if (state.phase === "error") {
    return (
      <div>
        <p className="screen-message">Не удалось загрузить форму: {state.message}</p>
        <Button className="action-button" size="l" stretched mode="outline" onClick={onCancel}>
          Назад
        </Button>
      </div>
    );
  }
  if (state.phase === "not_ready") {
    return (
      <div>
        <p className="screen-message">
          {STATUS_MESSAGES[state.status] ?? `Форма пока недоступна (статус: ${state.status}).`}
        </p>
        <Button className="action-button" size="l" stretched mode="outline" onClick={onCancel}>
          Назад
        </Button>
      </div>
    );
  }
  if (state.phase === "anomaly_confirm") {
    return (
      <div>
        <p className="plan-title">Результат выглядит необычно</p>
        <div className="anomaly-card">
          {state.result.anomalies_a && <AnomalyLines flags={state.result.anomalies_a} />}
          {state.result.anomalies_b && <AnomalyLines flags={state.result.anomalies_b} />}
        </div>
        <Button
          className="action-button"
          size="l"
          stretched
          disabled={submitting}
          onClick={() => void handleSubmit(state.plan, true)}
        >
          Всё верно
        </Button>
        <Button
          className="action-button"
          size="l"
          stretched
          mode="outline"
          disabled={submitting}
          onClick={() => setState({ phase: "form", plan: state.plan })}
        >
          Исправить
        </Button>
      </div>
    );
  }

  const { plan } = state;
  return (
    <div>
      <p className="plan-title">Добавить за дату</p>

      <label className="backdate-date-field">
        <span className="field-label">Дата тренировки</span>
        <input
          className="set-input"
          type="date"
          max={TODAY}
          aria-label="Дата тренировки"
          value={performedAt}
          onChange={(e) => setPerformedAt(e.target.value)}
        />
      </label>

      <BlockForm
        letter="A"
        target={plan.target_a}
        workSets={plan.work_sets_a}
        equipmentType={plan.equipment_a?.type}
        equipmentLabel={plan.equipment_a?.label}
        workingValues={blockAWorking}
        onWorkingChangeAt={(index, value) => setBlockAWorking((prev) => replaceAt(prev, index, value))}
        maxValue={blockAMax}
        onMaxChange={setBlockAMax}
        actualWeightValue={blockAActualWeight}
        onActualWeightChange={setBlockAActualWeight}
        bandItems={plan.band_items}
        bandItemValue={blockABandItem}
        onBandItemChange={setBlockABandItem}
      />

      <BlockForm
        letter="B"
        target={plan.target_b}
        workSets={plan.work_sets_b}
        equipmentType={plan.equipment_b?.type}
        equipmentLabel={plan.equipment_b?.label}
        workingValues={blockBWorking}
        onWorkingChangeAt={(index, value) => setBlockBWorking((prev) => replaceAt(prev, index, value))}
        maxValue={blockBMax}
        onMaxChange={setBlockBMax}
        actualWeightValue={blockBActualWeight}
        onActualWeightChange={setBlockBActualWeight}
        bandItems={plan.band_items}
        bandItemValue={blockBBandItem}
        onBandItemChange={setBlockBBandItem}
      />

      <Textarea header="Комментарий (необязательно)" value={comment} onChange={(e) => setComment(e.target.value)} />

      {formError && <p className="error-banner">{formError}</p>}
      <Button
        className="action-button"
        size="l"
        stretched
        disabled={submitting}
        onClick={() => void handleSubmit(plan, false)}
      >
        Записать тренировку
      </Button>
      <Button className="action-button" size="l" stretched mode="outline" disabled={submitting} onClick={onCancel}>
        Отмена
      </Button>
    </div>
  );
}
