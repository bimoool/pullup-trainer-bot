import { Button, Textarea } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  cancelTimer,
  deleteWorkoutDraft,
  fetchTimerPreferences,
  fetchTimerStatus,
  fetchWorkoutDraft,
  fetchWorkoutPlan,
  saveWorkoutDraft,
  submitWorkout,
  type TimerPreferences,
  type WorkoutDraftRequest,
  type WorkoutPlanResponse,
  type WorkoutSubmitRequest,
  type WorkoutSubmitResponse,
} from "./api";
import { ensureAudioUnlocked } from "./sound";
import { TimerScreen } from "./TimerScreen";
import { AnomalyLines, BlockForm, STATUS_MESSAGES, parseOptionalWeight, parseSetValue, parseSetValues, replaceAt } from "./WorkoutScreen";

type Props = {
  initDataRaw: string;
  onCancel: () => void;
  onDone: () => void;
  /** Пока этот экран смонтирован, идёт живая тренировка — WorkoutScreen
   * пробрасывает это состояние наверх в App.tsx, чтобы переключение вкладок
   * не потеряло молча несохранённый ввод (issue #59, волна 2). */
  onActiveChange?: (active: boolean) => void;
};

// Пауза между блоками A и Б (issue #59) — тот же контент, что бот
// показывает на "Отдых 15 минут. Хочешь доп. упражнения во время отдыха?"
// (app/bot/texts.py::OPTIONAL_EXERCISE_*), продублирован как константа
// фронтенда: контент полностью статический, не персонализированный,
// заводить отдельный read-only эндпойнт ради двух неизменных строк не
// имеет смысла (тот же случай, что STATUS_MESSAGES выше в этом файле).
const PAUSE_EXERCISES: { label: string; details: string }[] = [
  { label: "Приседания", details: "5 подходов по 10 повторений. Отдых между подходами — минута." },
  { label: "Выпады (продвинутый уровень)", details: "5 подходов по 10 повторений. Отдых между подходами — минута." },
];

function PauseExercises() {
  const [selected, setSelected] = useState<number | null>(null);
  return (
    <div className="pause-exercises">
      <p className="field-label">Чем занять большой перерыв (по желанию)</p>
      <div className="workout-mode-buttons">
        {PAUSE_EXERCISES.map((exercise, index) => (
          <Button
            key={exercise.label}
            mode={selected === index ? "filled" : "outline"}
            size="s"
            onClick={() => setSelected(index)}
          >
            {exercise.label}
          </Button>
        ))}
      </div>
      {selected !== null && <p className="hint">{PAUSE_EXERCISES[selected].details}</p>}
    </div>
  );
}

type LiveStep =
  | { kind: "input"; block: "A" | "B"; isMax: boolean; index: number }
  | { kind: "rest"; block: "A" | "B"; setNumber: number }
  | { kind: "big_break" };

function buildSteps(workSetsA: number, workSetsB: number): LiveStep[] {
  const steps: LiveStep[] = [];
  for (let i = 0; i < workSetsA; i++) {
    steps.push({ kind: "input", block: "A", isMax: false, index: i });
    steps.push({ kind: "rest", block: "A", setNumber: i + 1 });
  }
  steps.push({ kind: "input", block: "A", isMax: true, index: workSetsA });
  steps.push({ kind: "rest", block: "A", setNumber: workSetsA + 1 });
  steps.push({ kind: "big_break" });
  for (let i = 0; i < workSetsB; i++) {
    steps.push({ kind: "input", block: "B", isMax: false, index: i });
    steps.push({ kind: "rest", block: "B", setNumber: i + 1 });
  }
  // Последний подход блока Б без завершающего отдыха (issue #59) — сразу
  // на сводный экран правки.
  steps.push({ kind: "input", block: "B", isMax: true, index: workSetsB });
  return steps;
}

/** Восстановленный черновик (issue #61) хранит только уже введённые
 * повторения — короче итогового числа рабочих подходов, остаток
 * дозаполняется пустыми строками для тех же полей ввода, что использует
 * обычный ход тренировки (BlockForm/set-grid). */
function padWorkingReps(reps: number[], length: number): string[] {
  const padded = Array<string>(length).fill("");
  reps.forEach((value, index) => {
    if (index < length) {
      padded[index] = String(value);
    }
  });
  return padded;
}

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "not_ready"; status: string }
  | { phase: "intro"; plan: WorkoutPlanResponse; prefs: TimerPreferences; steps: LiveStep[] }
  | { phase: "step"; plan: WorkoutPlanResponse; prefs: TimerPreferences; steps: LiveStep[]; stepIndex: number }
  | { phase: "review"; plan: WorkoutPlanResponse; result?: WorkoutSubmitResponse }
  | { phase: "done"; result: WorkoutSubmitResponse };

/**
 * Режим тренировки в реальном времени (issue #59, волна 2) — подход →
 * таймер отдыха → ввод результата этого подхода → следующий подход → ... →
 * сводный экран правки перед финальной отправкой через тот же
 * submit_workout, что и обычная форма WorkoutScreen (не отдельный
 * эндпойнт на каждый подход — промежуточные результаты держатся в этом
 * компоненте до финальной отправки).
 *
 * Промежуточные результаты каждого завершённого подхода сохраняются на
 * сервере черновиком (issue #61, GET/PUT/DELETE /api/workout/draft) — при
 * заходе на этот экран, если черновик найден, экран восстанавливается
 * ровно на том шаге, где остановился пользователь (тот же блок, тот же
 * подход, тот же таймер отдыха, если он ещё активен — см. TimerScreen),
 * а не начинается заново. Черновика нет — обычный старт с "intro"; если
 * при этом на сервере всё же остался активный таймер (переходный период
 * после этого фикса/старые протухшие записи), он на всякий случай
 * отменяется, как и раньше.
 */
export function LiveWorkoutScreen({ initDataRaw, onCancel, onDone, onActiveChange }: Props) {
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
  const [inputValue, setInputValue] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    onActiveChange?.(true);
    return () => onActiveChange?.(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [status, draft, plan, prefs] = await Promise.all([
          fetchTimerStatus(initDataRaw),
          fetchWorkoutDraft(initDataRaw),
          fetchWorkoutPlan(initDataRaw),
          fetchTimerPreferences(initDataRaw),
        ]);
        if (cancelled) {
          return;
        }
        if (plan.status !== "ready") {
          setState({ phase: "not_ready", status: plan.status });
          return;
        }
        const workSetsA = plan.work_sets_a ?? 0;
        const workSetsB = plan.work_sets_b ?? 0;
        const steps = buildSteps(workSetsA, workSetsB);

        // Восстановление черновика (issue #61) — только если он реально
        // согласуется с текущим планом (число рабочих подходов не могло
        // измениться под незавершённым черновиком в норме, но не
        // полагаемся на это слепо: расхождение — сигнал отбросить черновик
        // и начать как обычно, а не подставлять данные не под тот план).
        if (
          draft.active
          && draft.block_a_working_reps !== null
          && draft.block_b_working_reps !== null
          && draft.step_index !== null
          && draft.block_a_working_reps.length <= workSetsA
          && draft.block_b_working_reps.length <= workSetsB
        ) {
          setBlockAWorking(padWorkingReps(draft.block_a_working_reps, workSetsA));
          setBlockAMax(draft.block_a_max_reps !== null ? String(draft.block_a_max_reps) : "");
          setBlockBWorking(padWorkingReps(draft.block_b_working_reps, workSetsB));
          setBlockBMax(draft.block_b_max_reps !== null ? String(draft.block_b_max_reps) : "");
          setBlockAActualWeight(draft.block_a_actual_weight ?? "");
          setBlockBActualWeight(draft.block_b_actual_weight ?? "");
          setBlockABandItem(
            draft.block_a_actual_band_item_id !== null ? String(draft.block_a_actual_band_item_id) : "",
          );
          setBlockBBandItem(
            draft.block_b_actual_band_item_id !== null ? String(draft.block_b_actual_band_item_id) : "",
          );
          setComment(draft.comment ?? "");
          if (draft.step_index < steps.length) {
            setState({ phase: "step", plan, prefs, steps, stepIndex: draft.step_index });
          } else {
            setState({ phase: "review", plan });
          }
          return;
        }

        if (status.active) {
          // Активный таймер без черновика — не должно возникать при
          // обычном потоке после этого фикса (черновик создаётся раньше
          // первого таймера, см. "Начать" ниже), но подстраховка на
          // переходный период/старые протухшие записи: начинаем заново.
          await cancelTimer(initDataRaw);
        }
        setBlockAWorking(Array(workSetsA).fill(""));
        setBlockBWorking(Array(workSetsB).fill(""));
        setState({ phase: "intro", plan, prefs, steps });
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

  function goToStep(plan: WorkoutPlanResponse, prefs: TimerPreferences, steps: LiveStep[], nextIndex: number) {
    if (nextIndex >= steps.length) {
      setState({ phase: "review", plan });
      return;
    }
    setInputValue("");
    setState({ phase: "step", plan, prefs, steps, stepIndex: nextIndex });
  }

  /** Черновик тренировки (issue #61) — сохраняет накопленный прогресс на
   * сервере после каждого завершённого подхода, весь массив разом (не
   * один подход). actualWeight/bandItem/comment персистятся как есть —
   * они не редактируются на шагах ввода (только на review), поэтому здесь
   * это либо ещё пустые значения, либо то, что уже было в восстановленном
   * черновике. */
  function buildDraftBody(
    stepIndex: number,
    workingA: string[],
    maxA: string,
    workingB: string[],
    maxB: string,
  ): WorkoutDraftRequest {
    const actualWeightA = parseOptionalWeight(blockAActualWeight);
    const actualWeightB = parseOptionalWeight(blockBActualWeight);
    return {
      step_index: stepIndex,
      block_a_working_reps: parseSetValues(workingA.filter((v) => v !== "")) ?? [],
      block_a_max_reps: parseSetValue(maxA),
      block_b_working_reps: parseSetValues(workingB.filter((v) => v !== "")) ?? [],
      block_b_max_reps: parseSetValue(maxB),
      block_a_actual_weight: actualWeightA.ok ? actualWeightA.value : null,
      block_b_actual_weight: actualWeightB.ok ? actualWeightB.value : null,
      block_a_actual_band_item_id: blockABandItem ? Number(blockABandItem) : null,
      block_b_actual_band_item_id: blockBBandItem ? Number(blockBBandItem) : null,
      comment: comment.trim() || null,
    };
  }

  /** Завершение шага ввода подхода — сохраняет черновик на сервере ДО
   * перехода на следующий шаг (issue #61) и ждёт ответа, в отличие от
   * best-effort cancelTimer/deleteWorkoutDraft ниже: если сохранение не
   * удалось, показываем ошибку и не продолжаем — иначе только что
   * введённый подход потерялся бы молча при следующем закрытии Telegram. */
  async function handleStepDone(
    plan: WorkoutPlanResponse,
    prefs: TimerPreferences,
    steps: LiveStep[],
    stepIndex: number,
    step: Extract<LiveStep, { kind: "input" }>,
  ) {
    const parsed = parseSetValue(inputValue);
    if (parsed === null) {
      setFormError("Введи число повторений.");
      return;
    }
    setFormError(null);
    ensureAudioUnlocked();

    let nextWorkingA = blockAWorking;
    let nextMaxA = blockAMax;
    let nextWorkingB = blockBWorking;
    let nextMaxB = blockBMax;
    if (step.block === "A") {
      if (step.isMax) {
        nextMaxA = String(parsed);
      } else {
        nextWorkingA = replaceAt(blockAWorking, step.index, String(parsed));
      }
    } else {
      if (step.isMax) {
        nextMaxB = String(parsed);
      } else {
        nextWorkingB = replaceAt(blockBWorking, step.index, String(parsed));
      }
    }

    const nextStepIndex = stepIndex + 1;
    setSubmitting(true);
    try {
      await saveWorkoutDraft(initDataRaw, buildDraftBody(nextStepIndex, nextWorkingA, nextMaxA, nextWorkingB, nextMaxB));
    } catch (error) {
      setSubmitting(false);
      setFormError(
        `Не удалось сохранить подход: ${error instanceof Error ? error.message : String(error)}. Попробуй ещё раз.`,
      );
      return;
    }
    setSubmitting(false);

    if (step.block === "A") {
      if (step.isMax) {
        setBlockAMax(nextMaxA);
      } else {
        setBlockAWorking(nextWorkingA);
      }
    } else if (step.isMax) {
      setBlockBMax(nextMaxB);
    } else {
      setBlockBWorking(nextWorkingB);
    }
    goToStep(plan, prefs, steps, nextStepIndex);
  }

  function buildSubmitBody(confirmAnomalies: boolean): WorkoutSubmitRequest {
    const actualWeightA = parseOptionalWeight(blockAActualWeight);
    const actualWeightB = parseOptionalWeight(blockBActualWeight);
    return {
      block_a_working_reps: parseSetValues(blockAWorking) ?? [],
      block_a_max_reps: parseSetValue(blockAMax) ?? 0,
      block_b_working_reps: parseSetValues(blockBWorking) ?? [],
      block_b_max_reps: parseSetValue(blockBMax) ?? 0,
      block_a_actual_weight: actualWeightA.ok ? actualWeightA.value : null,
      block_b_actual_weight: actualWeightB.ok ? actualWeightB.value : null,
      block_a_actual_band_item_id: blockABandItem ? Number(blockABandItem) : null,
      block_b_actual_band_item_id: blockBBandItem ? Number(blockBBandItem) : null,
      comment: comment.trim() || null,
      confirm_anomalies: confirmAnomalies,
    };
  }

  async function handleFinalSubmit(plan: WorkoutPlanResponse, confirmAnomalies: boolean) {
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

    const body = buildSubmitBody(confirmAnomalies);
    setSubmitting(true);
    try {
      const result = await submitWorkout(initDataRaw, body);
      if (result.status === "anomaly_confirm_required") {
        setState({ phase: "review", plan, result });
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

  async function handleCancelAll() {
    ensureAudioUnlocked();
    try {
      await Promise.all([cancelTimer(initDataRaw), deleteWorkoutDraft(initDataRaw)]);
    } catch {
      // Лучшее усилие — отмена таймера/черновика не должна блокировать выход.
    }
    onCancel();
  }

  if (state.phase === "loading") {
    return <p className="screen-message">Загружаю план тренировки…</p>;
  }
  if (state.phase === "error") {
    return (
      <div>
        <p className="screen-message">Не удалось загрузить план: {state.message}</p>
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

  if (state.phase === "intro") {
    const { plan, prefs, steps } = state;
    return (
      <div>
        <p className="plan-title">Тренировка в реальном времени</p>
        <p className="screen-message">
          Блок A — цель {plan.target_a} ({plan.equipment_a?.label}), блок Б — цель {plan.target_b} (
          {plan.equipment_b?.label}). После каждого подхода — таймер отдыха, между блоками — большой перерыв.
        </p>
        <Button
          className="action-button"
          size="l"
          stretched
          onClick={() => {
            ensureAudioUnlocked();
            // Создаём черновик до первого шага (issue #61) — best-effort:
            // на этот момент ещё нет ни одного введённого подхода, терять
            // нечего, блокировать переход ожиданием ответа незачем.
            saveWorkoutDraft(initDataRaw, buildDraftBody(0, [], "", [], "")).catch(() => {});
            goToStep(plan, prefs, steps, 0);
          }}
        >
          Начать
        </Button>
        <Button className="action-button" size="l" stretched mode="outline" onClick={() => void handleCancelAll()}>
          Отмена
        </Button>
      </div>
    );
  }

  if (state.phase === "step") {
    const { plan, prefs, steps, stepIndex } = state;
    const step = steps[stepIndex];

    if (step.kind === "big_break") {
      return (
        <TimerScreen
          key={stepIndex}
          initDataRaw={initDataRaw}
          timerType="big_break"
          blockLetter={null}
          setNumber={null}
          title="Большой перерыв между блоками"
          defaultDurationSeconds={prefs.big_break_seconds}
          onDone={() => goToStep(plan, prefs, steps, stepIndex + 1)}
        >
          <PauseExercises />
        </TimerScreen>
      );
    }

    if (step.kind === "rest") {
      const defaultDuration = step.block === "A" ? prefs.rest_seconds_block_a : prefs.rest_seconds_block_b;
      return (
        <TimerScreen
          key={stepIndex}
          initDataRaw={initDataRaw}
          timerType="rest_between_sets"
          blockLetter={step.block}
          setNumber={step.setNumber}
          title={`Отдых — блок ${step.block}`}
          defaultDurationSeconds={defaultDuration}
          onDone={() => goToStep(plan, prefs, steps, stepIndex + 1)}
        />
      );
    }

    const setLabel = step.isMax
      ? "Подход на максимум"
      : `Рабочий подход ${step.index + 1} из ${step.block === "A" ? plan.work_sets_a : plan.work_sets_b}`;
    return (
      <div>
        <p className="plan-title">
          Блок {step.block} — {setLabel}
        </p>
        <div className="set-grid">
          <input
            className="set-input max-input"
            type="number"
            inputMode="numeric"
            min={0}
            max={999}
            autoFocus
            aria-label={`Блок ${step.block}, ${setLabel}`}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
          />
        </div>
        {formError && <p className="error-banner">{formError}</p>}
        <Button
          className="action-button"
          size="l"
          stretched
          disabled={submitting}
          onClick={() => void handleStepDone(plan, prefs, steps, stepIndex, step)}
        >
          Готово
        </Button>
        <Button className="action-button" size="l" stretched mode="outline" onClick={() => void handleCancelAll()}>
          Отмена
        </Button>
      </div>
    );
  }

  if (state.phase === "review") {
    const { plan, result } = state;
    if (result?.status === "anomaly_confirm_required") {
      return (
        <div>
          <p className="plan-title">Результат выглядит необычно</p>
          <div className="anomaly-card">
            {result.anomalies_a && <AnomalyLines flags={result.anomalies_a} />}
            {result.anomalies_b && <AnomalyLines flags={result.anomalies_b} />}
          </div>
          <Button
            className="action-button"
            size="l"
            stretched
            disabled={submitting}
            onClick={() => void handleFinalSubmit(plan, true)}
          >
            Всё верно
          </Button>
          <Button
            className="action-button"
            size="l"
            stretched
            mode="outline"
            disabled={submitting}
            onClick={() => setState({ phase: "review", plan })}
          >
            Исправить
          </Button>
        </div>
      );
    }

    return (
      <div>
        <p className="plan-title">Проверь результаты перед отправкой</p>

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
          onClick={() => void handleFinalSubmit(plan, false)}
        >
          Записать тренировку
        </Button>
      </div>
    );
  }

  const { result } = state;
  return (
    <div className="done-card">
      <div className="done-check">✓</div>
      <p className="done-title">Тренировка записана</p>
      <div className="done-stats">
        <p>Блок A: {result.result_a}</p>
        <p>Блок B: {result.result_b}</p>
        <p className="hint">
          Цели на следующую тренировку: блок A — {result.target_a} ({result.equipment_a?.label}), блок B —{" "}
          {result.target_b} ({result.equipment_b?.label}).
        </p>
      </div>
      <Button className="action-button" size="l" stretched onClick={onDone}>
        Готово
      </Button>
    </div>
  );
}
