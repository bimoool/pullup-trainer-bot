import { useEffect, useState } from "react";

import {
  fetchWorkoutPlan,
  submitWorkout,
  type AnomalyFlags,
  type WorkoutPlanResponse,
  type WorkoutSubmitRequest,
  type WorkoutSubmitResponse,
} from "./api";

type Props = { initDataRaw: string };

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "not_ready"; status: string }
  | { phase: "form"; plan: WorkoutPlanResponse }
  | { phase: "anomaly_confirm"; plan: WorkoutPlanResponse; body: WorkoutSubmitRequest; result: WorkoutSubmitResponse }
  | { phase: "done"; result: WorkoutSubmitResponse };

// Текст для статусов, которые Mini App Этапа 1 не обрабатывает формой
// (сужение скоупа, issue #36) — та же причина, что определила бы ветку в
// handle_start_workout бота (app/bot/handlers/workout.py), просто без
// самого диалога. Пользователь продолжает в боте, ничего не теряя —
// у бота эти случаи по-прежнему работают как раньше.
const STATUS_MESSAGES: Record<string, string> = {
  no_access: "Нет активной подписки. Оформи её в боте, потом возвращайся сюда.",
  first_workout: "Это твоя первая тренировка — замер и выбор снаряда пока доступны только в боте.",
  too_early: "Ещё рано для следующей тренировки — минимальный отдых между тренировками не прошёл.",
  gap_retest_required: "Был долгий перерыв — нужен повторный замер, начни его в боте.",
  deload_due: "Пора на разгрузочную тренировку блока на объём — эта форма пока доступна только в боте.",
  equipment_setup_required: "Нужно заново выбрать снаряд для одного из блоков — сделай это в боте.",
  no_active_set: "Не получилось открыть тренировочный цикл. Напиши в поддержку через бота.",
  not_onboarded: "Похоже, ты ещё не проходил онбординг — начни его в боте.",
};

function closeMiniApp() {
  (window as unknown as { Telegram?: { WebApp?: { close?: () => void } } }).Telegram?.WebApp?.close?.();
}

function parseReps(raw: string): number[] | null {
  const parts = raw.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return null;
  }
  const numbers = parts.map(Number);
  if (numbers.some((n) => !Number.isInteger(n) || n < 0)) {
    return null;
  }
  return numbers;
}

function AnomalyLines({ flags }: { flags: AnomalyFlags }) {
  return (
    <ul>
      {flags.large_value !== null && <li>Необычно большое число: {flags.large_value}.</li>}
      {flags.previous_avg !== null && (
        <li>
          Резкий скачок относительно прошлой тренировки: было в среднем {flags.previous_avg}, сейчас{" "}
          {flags.current_avg}.
        </li>
      )}
      {flags.actual_set_count !== null && (
        <li>
          Ожидалось {flags.expected_set_count} рабочих подходов, введено {flags.actual_set_count}.
        </li>
      )}
    </ul>
  );
}

export function WorkoutScreen({ initDataRaw }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
  const [blockAWorking, setBlockAWorking] = useState("");
  const [blockAMax, setBlockAMax] = useState("");
  const [blockBWorking, setBlockBWorking] = useState("");
  const [blockBMax, setBlockBMax] = useState("");
  const [comment, setComment] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const plan = await fetchWorkoutPlan(initDataRaw);
        if (cancelled) {
          return;
        }
        setState(plan.status === "ready" ? { phase: "form", plan } : { phase: "not_ready", status: plan.status });
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
    const workingA = parseReps(blockAWorking);
    const maxA = parseReps(blockAMax);
    const workingB = parseReps(blockBWorking);
    const maxB = parseReps(blockBMax);
    if (!workingA || !maxA || maxA.length !== 1 || !workingB || !maxB || maxB.length !== 1) {
      setFormError("Проверь ввод — рабочие подходы и подход на максимум должны быть числами через пробел.");
      return;
    }
    setFormError(null);

    const body: WorkoutSubmitRequest = {
      block_a_working_reps: workingA,
      block_a_max_reps: maxA[0],
      block_b_working_reps: workingB,
      block_b_max_reps: maxB[0],
      comment: comment.trim() || null,
      confirm_anomalies: confirmAnomalies,
    };

    setSubmitting(true);
    try {
      const result = await submitWorkout(initDataRaw, body);
      if (result.status === "anomaly_confirm_required") {
        setState({ phase: "anomaly_confirm", plan, body, result });
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
    return <p>Загружаю план тренировки…</p>;
  }
  if (state.phase === "error") {
    return <p>Не удалось загрузить план: {state.message}</p>;
  }
  if (state.phase === "not_ready") {
    return (
      <div>
        <p>{STATUS_MESSAGES[state.status] ?? `Форма пока недоступна (статус: ${state.status}).`}</p>
        <button onClick={closeMiniApp}>Открыть в боте</button>
      </div>
    );
  }
  if (state.phase === "anomaly_confirm") {
    return (
      <div>
        <p>Результат выглядит необычно — всё верно?</p>
        {state.result.anomalies_a && <AnomalyLines flags={state.result.anomalies_a} />}
        {state.result.anomalies_b && <AnomalyLines flags={state.result.anomalies_b} />}
        <button disabled={submitting} onClick={() => void handleSubmit(state.plan, true)}>
          Всё верно
        </button>
        <button disabled={submitting} onClick={() => setState({ phase: "form", plan: state.plan })}>
          Исправить
        </button>
      </div>
    );
  }
  if (state.phase === "done") {
    const { result } = state;
    return (
      <div>
        <h2>Тренировка записана</h2>
        <p>Блок A: {result.result_a}</p>
        <p>Блок B: {result.result_b}</p>
        <p>
          Цели на следующую тренировку: блок A — {result.target_a} ({result.equipment_a?.label}), блок B —{" "}
          {result.target_b} ({result.equipment_b?.label}).
        </p>
      </div>
    );
  }

  const { plan } = state;
  return (
    <div>
      <h2>Текущий план</h2>
      {plan.is_gap_rollback && <p>Был перерыв — цель блока A немного снижена, это нормально.</p>}
      <p>
        Блок A: цель {plan.target_a}, {plan.work_sets_a} рабочих подхода, снаряд — {plan.equipment_a?.label}.
      </p>
      <label>
        Рабочие подходы блока A (через пробел)
        <input value={blockAWorking} onChange={(e) => setBlockAWorking(e.target.value)} />
      </label>
      <label>
        Подход блока A на максимум
        <input value={blockAMax} onChange={(e) => setBlockAMax(e.target.value)} />
      </label>

      <p>
        Блок B: цель {plan.target_b}, {plan.work_sets_b} рабочих подхода, снаряд — {plan.equipment_b?.label}.
      </p>
      <label>
        Рабочие подходы блока B (через пробел)
        <input value={blockBWorking} onChange={(e) => setBlockBWorking(e.target.value)} />
      </label>
      <label>
        Подход блока B на максимум
        <input value={blockBMax} onChange={(e) => setBlockBMax(e.target.value)} />
      </label>

      <label>
        Комментарий (необязательно)
        <textarea value={comment} onChange={(e) => setComment(e.target.value)} />
      </label>

      {formError && <p>{formError}</p>}
      <button disabled={submitting} onClick={() => void handleSubmit(plan, false)}>
        Записать тренировку
      </button>
    </div>
  );
}
