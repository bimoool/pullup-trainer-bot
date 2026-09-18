import { Button, Placeholder, Section, Spinner, Textarea } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  fetchFreeWorkoutPlan,
  submitFreeWorkout,
  type FreeWorkoutPlan,
  type FreeWorkoutSubmitResponse,
} from "./api";
import { EquipmentTypeFields, type EquipmentChoice } from "./BackdateForm";
import { AnomalyLines, SetInputGrid, parseSetValue, parseSetValues, replaceAt } from "./WorkoutScreen";

type Props = {
  initDataRaw: string;
  onDone: () => void;
  onCancel: () => void;
};

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "not_ready"; status: string }
  | { phase: "form"; plan: FreeWorkoutPlan }
  | { phase: "anomaly_confirm"; plan: FreeWorkoutPlan; result: FreeWorkoutSubmitResponse }
  | { phase: "done"; result: FreeWorkoutSubmitResponse };

// Нет "no_access" (свободные подтягивания не за паивеллом, как и факультатив
// — см. app/web/routes.py::get_free_workout_plan) и нет too_early/gap_retest_
// required/deload_due/equipment_setup_required — они про готовность к
// ОБЫЧНОЙ тренировке, свободный вход вне цикла программы этим не гейтуется.
const STATUS_MESSAGES: Record<string, string> = {
  no_active_set: "Не получилось открыть тренировочный цикл. Напиши в поддержку через бота.",
  not_onboarded: "Похоже, ты ещё не проходил онбординг — начни его в боте.",
};

const MIN_SETS = 1;
const MAX_SETS = 20;

/**
 * Форма "Внести свободные подтягивания" (issue #109) — блок A вне цикла
 * программы, произвольное число рабочих подходов (issue #88/#109: сколько
 * реально сделал, столько и вводит, не фиксированные 3+1 обычного блока A) +
 * подход на максимум + явный выбор снаряда (тот же EquipmentTypeFields, что
 * и у бэкдейта — снаряд здесь тоже не наследуется молча). Тот же backend-путь,
 * что и у бота (WorkoutLogService.record_free_workout, не отдельная копия).
 *
 * `Placeholder`/`Spinner` вместо `.screen-message` на состояниях загрузки/
 * ошибки/недоступности (issue #142) — тот же базовый паттерн, что
 * AchievementsScreen.tsx. Раскладка ввода подходов (`SetInputGrid`,
 * `.block-section`/`.workout-mode-buttons`/`.set-grid`/`.field-label`) и
 * общие layout-классы (`.plan-title`/`.action-button`/`.error-banner`/
 * `.done-card`/`.anomaly-card`) не тронуты — общие с ещё немигрированным
 * WorkoutScreen.tsx, чистка/замена — в финальном PR 7 по плану.
 */
export function FreeWorkoutScreen({ initDataRaw, onDone, onCancel }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
  const [working, setWorking] = useState<string[]>(Array(3).fill(""));
  const [maxReps, setMaxReps] = useState("");
  const [equipment, setEquipment] = useState<EquipmentChoice>({ type: "bodyweight", value: "", bandItemId: "" });
  const [comment, setComment] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const plan = await fetchFreeWorkoutPlan(initDataRaw);
        if (cancelled) {
          return;
        }
        if (plan.status === "ready") {
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

  async function handleSubmit(plan: FreeWorkoutPlan, confirmAnomalies: boolean) {
    const workingReps = parseSetValues(working);
    const max = parseSetValue(maxReps);
    if (workingReps === null || max === null) {
      setFormError("Заполни все подходы числами — пустые или нечисловые поля недопустимы.");
      return;
    }
    if (equipment.type === "weight" && !(Number(equipment.value) > 0)) {
      setFormError("Укажи вес.");
      return;
    }
    if (equipment.type === "band" && !equipment.bandItemId) {
      setFormError("Выбери резину.");
      return;
    }
    setFormError(null);

    setSubmitting(true);
    try {
      const result = await submitFreeWorkout(initDataRaw, {
        working_reps: workingReps,
        max_reps: max,
        equipment_type: equipment.type,
        equipment_value: equipment.type === "weight" ? equipment.value : null,
        equipment_item_id: equipment.type === "band" ? Number(equipment.bandItemId) : null,
        comment: comment.trim() || null,
        confirm_anomalies: confirmAnomalies,
      });
      if (result.status === "anomaly_confirm_required") {
        setState({ phase: "anomaly_confirm", plan, result });
        return;
      }
      if (result.status !== "ok") {
        setState({ phase: "not_ready", status: result.status });
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
    return (
      <Placeholder>
        <Spinner size="m" />
      </Placeholder>
    );
  }
  if (state.phase === "error") {
    return (
      <div>
        <Placeholder description={`Не удалось загрузить форму: ${state.message}`} />
        <Button className="action-button" size="l" stretched mode="outline" onClick={onCancel}>
          Назад
        </Button>
      </div>
    );
  }
  if (state.phase === "not_ready") {
    return (
      <div>
        <Placeholder description={STATUS_MESSAGES[state.status] ?? `Форма пока недоступна (статус: ${state.status}).`} />
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
        <div className="anomaly-card">{state.result.anomalies && <AnomalyLines flags={state.result.anomalies} />}</div>
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
  if (state.phase === "done") {
    const { result } = state;
    return (
      <div className="done-card">
        <div className="done-check">✓</div>
        <p className="done-title">Свободные подтягивания записаны</p>
        <div className="done-stats">
          <p>{result.result_text}</p>
          {result.equipment && <p className="hint">Снаряд — {result.equipment.label}.</p>}
          <p className="hint">В план и текущий цикл это не входит — только статистика и общий объём.</p>
        </div>
        <Button className="action-button" size="l" stretched onClick={onDone}>
          Готово
        </Button>
      </div>
    );
  }

  const { plan } = state;
  return (
    <div>
      <p className="plan-title">Внести свободные подтягивания</p>

      <Section className="block-section" header="Рабочие подходы">
        <SetInputGrid
          values={working}
          onChangeAt={(index, value) => setWorking((prev) => replaceAt(prev, index, value))}
          ariaLabelPrefix="Подход"
        />
        <div className="workout-mode-buttons">
          <Button
            mode="outline"
            size="s"
            disabled={working.length <= MIN_SETS}
            onClick={() => setWorking((prev) => prev.slice(0, -1))}
          >
            − подход
          </Button>
          <Button
            mode="outline"
            size="s"
            disabled={working.length >= MAX_SETS}
            onClick={() => setWorking((prev) => [...prev, ""])}
          >
            + подход
          </Button>
        </div>

        <span className="field-label">Подход на максимум</span>
        <div className="set-grid">
          <input
            className="set-input max-input"
            type="number"
            inputMode="numeric"
            min={0}
            max={999}
            aria-label="Подход на максимум"
            value={maxReps}
            onChange={(e) => setMaxReps(e.target.value)}
          />
        </div>

        <EquipmentTypeFields
          letter="A"
          choice={equipment}
          onTypeChange={(value) => setEquipment({ type: value, value: "", bandItemId: "" })}
          onValueChange={(value) => setEquipment((prev) => ({ ...prev, value }))}
          onBandItemChange={(value) => setEquipment((prev) => ({ ...prev, bandItemId: value }))}
          bandItems={plan.band_items}
        />
      </Section>

      <Textarea header="Комментарий (необязательно)" value={comment} onChange={(e) => setComment(e.target.value)} />

      {formError && <p className="error-banner">{formError}</p>}
      <Button
        className="action-button"
        size="l"
        stretched
        disabled={submitting}
        onClick={() => void handleSubmit(state.plan, false)}
      >
        Записать
      </Button>
      <Button className="action-button" size="l" stretched mode="outline" disabled={submitting} onClick={onCancel}>
        Отмена
      </Button>
    </div>
  );
}
