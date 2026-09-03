import { Button, Textarea } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  fetchHistoryEntry,
  patchHistoryEntry,
  type HistoryEditDetail,
  type HistoryEditRequest,
  type WorkoutSubmitResponse,
} from "./api";
import { AnomalyLines, BlockForm, parseOptionalWeight, parseSetValue, parseSetValues, replaceAt } from "./BlockForm";

type Props = {
  initDataRaw: string;
  workoutId: number;
  onCancel: () => void;
  onSaved: () => void;
};

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "not_editable" }
  | { phase: "form"; detail: HistoryEditDetail }
  | { phase: "anomaly_confirm"; detail: HistoryEditDetail; body: HistoryEditRequest; result: WorkoutSubmitResponse };

/** Форма редактирования прошлой тренировки (issue #52, волна 2) — та же
 * BlockForm/анти-аномальный поток, что и WorkoutScreen.tsx, просто
 * предзаполненная из GET /api/history/{id} и отправляющая PATCH вместо
 * POST /api/workout/submit. targetLabel="цель до этой тренировки" — это
 * target_before отредактированной записи (тот же "пример формата", что
 * бот показывает через _format_block_a_prompt перед правкой), не цель на
 * следующую тренировку, как у формы живого ввода. */
export function HistoryEditForm({ initDataRaw, workoutId, onCancel, onSaved }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
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
        const detail = await fetchHistoryEntry(initDataRaw, workoutId);
        if (cancelled) {
          return;
        }
        if (!detail.is_editable) {
          setState({ phase: "not_editable" });
          return;
        }
        setBlockAWorking(detail.block_a.working_reps.map(String));
        setBlockAMax(String(detail.block_a.max_reps));
        setBlockBWorking(detail.block_b.working_reps.map(String));
        setBlockBMax(String(detail.block_b.max_reps));
        setComment(detail.comment ?? "");
        setState({ phase: "form", detail });
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
  }, [initDataRaw, workoutId]);

  async function handleSubmit(detail: HistoryEditDetail, confirmAnomalies: boolean) {
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

    const body: HistoryEditRequest = {
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
      const result = await patchHistoryEntry(initDataRaw, workoutId, body);
      if (result.status === "anomaly_confirm_required") {
        setState({ phase: "anomaly_confirm", detail, body, result });
        return;
      }
      if (result.status !== "ok") {
        setFormError(`Не удалось сохранить (статус: ${result.status}).`);
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
    return <p className="screen-message">Загружаю тренировку…</p>;
  }
  if (state.phase === "error") {
    return (
      <div>
        <p className="screen-message">Не удалось загрузить тренировку: {state.message}</p>
        <Button className="action-button" size="l" stretched mode="outline" onClick={onCancel}>
          Назад
        </Button>
      </div>
    );
  }
  if (state.phase === "not_editable") {
    return (
      <div>
        <p className="screen-message">
          Эта тренировка внесена задним числом или как свободный подход — редактировать её здесь нельзя.
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
          onClick={() => void handleSubmit(state.detail, true)}
        >
          Всё верно
        </Button>
        <Button
          className="action-button"
          size="l"
          stretched
          mode="outline"
          disabled={submitting}
          onClick={() => setState({ phase: "form", detail: state.detail })}
        >
          Исправить
        </Button>
      </div>
    );
  }

  const { detail } = state;
  return (
    <div>
      <p className="plan-title">Редактирование тренировки</p>

      <BlockForm
        letter="A"
        target={detail.block_a.target_before}
        targetLabel="цель до этой тренировки"
        workSets={detail.block_a.working_reps.length}
        equipmentType={detail.block_a.equipment.type}
        equipmentLabel={detail.block_a.equipment.label}
        workingValues={blockAWorking}
        onWorkingChangeAt={(index, value) => setBlockAWorking((prev) => replaceAt(prev, index, value))}
        maxValue={blockAMax}
        onMaxChange={setBlockAMax}
        actualWeightValue={blockAActualWeight}
        onActualWeightChange={setBlockAActualWeight}
        bandItems={detail.band_items}
        bandItemValue={blockABandItem}
        onBandItemChange={setBlockABandItem}
      />

      <BlockForm
        letter="B"
        target={detail.block_b.target_before}
        targetLabel="цель до этой тренировки"
        workSets={detail.block_b.working_reps.length}
        equipmentType={detail.block_b.equipment.type}
        equipmentLabel={detail.block_b.equipment.label}
        workingValues={blockBWorking}
        onWorkingChangeAt={(index, value) => setBlockBWorking((prev) => replaceAt(prev, index, value))}
        maxValue={blockBMax}
        onMaxChange={setBlockBMax}
        actualWeightValue={blockBActualWeight}
        onActualWeightChange={setBlockBActualWeight}
        bandItems={detail.band_items}
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
        onClick={() => void handleSubmit(detail, false)}
      >
        Сохранить
      </Button>
      <Button className="action-button" size="l" stretched mode="outline" disabled={submitting} onClick={onCancel}>
        Отмена
      </Button>
    </div>
  );
}
