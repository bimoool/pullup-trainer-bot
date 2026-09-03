import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  fetchHistoryDetail,
  patchHistoryEdit,
  type HistoryEditDetail,
  type HistoryEditRequest,
  type WorkoutSubmitResponse,
} from "./api";
import { AnomalyLines, BlockForm, parseOptionalWeight, parseSetValue, parseSetValues, replaceAt } from "./WorkoutScreen";

type Props = {
  initDataRaw: string;
  workoutId: number;
  onDone: () => void;
  onCancel: () => void;
};

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "form"; detail: HistoryEditDetail }
  | { phase: "anomaly_confirm"; detail: HistoryEditDetail; result: WorkoutSubmitResponse }
  | { phase: "done"; result: WorkoutSubmitResponse };

/** "2026-09-03" -> "03.09.2026" — тот же формат, что HistoryScreen.tsx. */
function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-");
  return `${day}.${month}.${year}`;
}

/**
 * Форма редактирования прошлой тренировки (issue #52) — та же разметка
 * блоков, что WorkoutScreen.tsx (BlockForm/AnomalyLines/парсинг оттуда же,
 * не копия), предзаполненная реально введёнными числами из
 * GET /api/history/{id}, сабмит через PATCH /api/history/{id}
 * (app.web.routes::edit_history_workout — тот же каскадный пересчёт, что
 * app.bot.handlers.workout_edit).
 *
 * Правка резины (в отличие от веса) здесь не предлагается — для неё нужен
 * бы личный список пользователя, а GET /api/history/{id} его не отдаёт
 * (не источник для этого списка нигде в проекте, кроме плана тренировки).
 * Осознанное сужение, не пропуск: правка веса (частый случай — "забыл
 * записать точный вес") доступна, смена резины — только через бота.
 */
export function HistoryEditForm({ initDataRaw, workoutId, onDone, onCancel }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
  const [blockAWorking, setBlockAWorking] = useState<string[]>([]);
  const [blockAMax, setBlockAMax] = useState("");
  const [blockBWorking, setBlockBWorking] = useState<string[]>([]);
  const [blockBMax, setBlockBMax] = useState("");
  const [blockAActualWeight, setBlockAActualWeight] = useState("");
  const [blockBActualWeight, setBlockBActualWeight] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const detail = await fetchHistoryDetail(initDataRaw, workoutId);
        if (cancelled) {
          return;
        }
        if (!detail.is_editable) {
          setState({ phase: "error", message: "Эта тренировка не редактируется (внесена задним числом)." });
          return;
        }
        setBlockAWorking(detail.block_a.working_reps.map(String));
        setBlockAMax(String(detail.block_a.max_reps));
        setBlockBWorking(detail.block_b.working_reps.map(String));
        setBlockBMax(String(detail.block_b.max_reps));
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
      confirm_anomalies: confirmAnomalies,
    };

    setSubmitting(true);
    try {
      const result = await patchHistoryEdit(initDataRaw, workoutId, body);
      if (result.status === "anomaly_confirm_required") {
        setState({ phase: "anomaly_confirm", detail, result });
        return;
      }
      if (result.status !== "ok") {
        setFormError(`Не удалось сохранить (статус: ${result.status}).`);
        return;
      }
      setState({ phase: "done", result });
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
        <p className="screen-message">{state.message}</p>
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
  if (state.phase === "done") {
    const { result } = state;
    return (
      <div className="done-card">
        <div className="done-check">✓</div>
        <p className="done-title">Тренировка обновлена</p>
        <div className="done-stats">
          <p>Блок A: {result.result_a}</p>
          <p>Блок B: {result.result_b}</p>
        </div>
        <Button className="action-button" size="l" stretched onClick={onDone}>
          Готово
        </Button>
      </div>
    );
  }

  const { detail } = state;
  return (
    <div>
      <p className="plan-title">Редактирование тренировки от {formatDate(detail.performed_at)}</p>

      <BlockForm
        letter="A"
        target={detail.block_a.target_before}
        workSets={detail.block_a.working_reps.length}
        equipmentType={detail.block_a.equipment.type}
        equipmentLabel={detail.block_a.equipment.label}
        workingValues={blockAWorking}
        onWorkingChangeAt={(index, value) => setBlockAWorking((prev) => replaceAt(prev, index, value))}
        maxValue={blockAMax}
        onMaxChange={setBlockAMax}
        actualWeightValue={blockAActualWeight}
        onActualWeightChange={setBlockAActualWeight}
        bandItems={[]}
        bandItemValue=""
        onBandItemChange={() => {}}
      />

      <BlockForm
        letter="B"
        target={detail.block_b.target_before}
        workSets={detail.block_b.working_reps.length}
        equipmentType={detail.block_b.equipment.type}
        equipmentLabel={detail.block_b.equipment.label}
        workingValues={blockBWorking}
        onWorkingChangeAt={(index, value) => setBlockBWorking((prev) => replaceAt(prev, index, value))}
        maxValue={blockBMax}
        onMaxChange={setBlockBMax}
        actualWeightValue={blockBActualWeight}
        onActualWeightChange={setBlockBActualWeight}
        bandItems={[]}
        bandItemValue=""
        onBandItemChange={() => {}}
      />

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
