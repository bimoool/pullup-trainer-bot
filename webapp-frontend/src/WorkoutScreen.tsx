import { Button, Input, Section, Select, Textarea } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  fetchWorkoutPlan,
  submitWorkout,
  type AnomalyFlags,
  type BandItemInfo,
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

/** Каждое поле — один подход, без разделителей и ручного парсинга строки. */
function parseSetValue(raw: string): number | null {
  const trimmed = raw.trim();
  if (!/^\d+$/.test(trimmed)) {
    return null;
  }
  return Number(trimmed);
}

function parseSetValues(values: string[]): number[] | null {
  if (values.length === 0) {
    return null;
  }
  const parsed = values.map(parseSetValue);
  if (parsed.some((n) => n === null)) {
    return null;
  }
  return parsed as number[];
}

function replaceAt(values: string[], index: number, value: string): string[] {
  return values.map((v, i) => (i === index ? value : v));
}

/** Пустое поле — правки нет (null, сервер оставит вес из прогрессии как
 * есть); непустое — должно быть положительным числом, как и живой ввод
 * веса в боте (app/bot/handlers/equipment.py::handle_equipment_value). */
function parseOptionalWeight(raw: string): { ok: true; value: string | null } | { ok: false } {
  const trimmed = raw.trim();
  if (trimmed === "") {
    return { ok: true, value: null };
  }
  const normalized = trimmed.replace(",", ".");
  const parsed = Number(normalized);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return { ok: false };
  }
  return { ok: true, value: normalized };
}

function AnomalyLines({ flags }: { flags: AnomalyFlags }) {
  return (
    <ul className="anomaly-list">
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

function SetInputGrid({
  values,
  onChangeAt,
  ariaLabelPrefix,
}: {
  values: string[];
  onChangeAt: (index: number, value: string) => void;
  ariaLabelPrefix: string;
}) {
  return (
    <div className="set-grid">
      {values.map((value, index) => (
        <label className="set-field" key={index}>
          <span>{index + 1}</span>
          <input
            className="set-input"
            type="number"
            inputMode="numeric"
            min={0}
            max={999}
            aria-label={`${ariaLabelPrefix} ${index + 1}`}
            value={value}
            onChange={(e) => onChangeAt(index, e.target.value)}
          />
        </label>
      ))}
    </div>
  );
}

function BandItemSelect({
  letter,
  bandItems,
  value,
  onChange,
}: {
  letter: "A" | "B";
  bandItems: BandItemInfo[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <Select
      header="Резина, если отличается"
      aria-label={`Блок ${letter}, резина`}
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">Как в прошлый раз</option>
      {bandItems.map((item) => (
        <option key={item.id} value={item.id}>
          {item.name}
          {item.resistance_kg !== null ? ` (${item.resistance_kg} кг)` : ""}
        </option>
      ))}
    </Select>
  );
}

function BlockForm({
  letter,
  target,
  workSets,
  equipmentType,
  equipmentLabel,
  workingValues,
  onWorkingChangeAt,
  maxValue,
  onMaxChange,
  actualWeightValue,
  onActualWeightChange,
  bandItems,
  bandItemValue,
  onBandItemChange,
}: {
  letter: "A" | "B";
  target: number | null;
  workSets: number | null;
  equipmentType: string | undefined;
  equipmentLabel: string | undefined;
  workingValues: string[];
  onWorkingChangeAt: (index: number, value: string) => void;
  maxValue: string;
  onMaxChange: (value: string) => void;
  actualWeightValue: string;
  onActualWeightChange: (value: string) => void;
  bandItems: BandItemInfo[];
  bandItemValue: string;
  onBandItemChange: (value: string) => void;
}) {
  return (
    <Section className="block-section" header={`Блок ${letter} — цель ${target}`}>
      <div className="block-header">
        <div className="block-badge">{letter}</div>
        <p className="block-subtitle">
          {workSets} рабочих {workSets === 1 ? "подход" : "подхода"} · {equipmentLabel ?? "снаряд не выбран"}
        </p>
      </div>

      <span className="field-label">Рабочие подходы</span>
      <SetInputGrid values={workingValues} onChangeAt={onWorkingChangeAt} ariaLabelPrefix={`Блок ${letter}, подход`} />

      <span className="field-label">Подход на максимум</span>
      <div className="set-grid">
        <input
          className="set-input max-input"
          type="number"
          inputMode="numeric"
          min={0}
          max={999}
          aria-label={`Блок ${letter}, подход на максимум`}
          value={maxValue}
          onChange={(e) => onMaxChange(e.target.value)}
        />
      </div>

      {/* Только для WEIGHT (issue #45, часть 2) — снаряд наследуется из
          прогрессии молча, реально взятый вес мог отличаться. У BAND/
          BODYWEIGHT/AUSTRALIAN "вес" не имеет отдельного смысла (см.
          app/web/routes.py::submit_workout — сервер игнорирует поле для
          остальных типов), поле здесь просто не показывается. */}
      {equipmentType === "weight" && (
        <Input
          header="Фактический вес (кг), если отличается"
          after="кг"
          type="number"
          inputMode="decimal"
          min={0}
          step="0.5"
          placeholder={equipmentLabel}
          aria-label={`Блок ${letter}, фактический вес`}
          value={actualWeightValue}
          onChange={(e) => onActualWeightChange(e.target.value)}
        />
      )}

      {/* Выбор резины (issue #48) — тот же принцип, что actual weight выше,
          только для BAND: снаряд наследуется молча, реально взятая резина
          могла отличаться. band_items пуст, если у пользователя ещё нет
          личного списка резин — тогда селект не показывается вовсе. */}
      {equipmentType === "band" && bandItems.length > 0 && (
        <BandItemSelect letter={letter} bandItems={bandItems} value={bandItemValue} onChange={onBandItemChange} />
      )}
    </Section>
  );
}

export function WorkoutScreen({ initDataRaw }: Props) {
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
        const plan = await fetchWorkoutPlan(initDataRaw);
        if (cancelled) {
          return;
        }
        if (plan.status === "ready") {
          // Динамическое число полей на подход (issue #38) — по
          // work_sets_a/work_sets_b из ответа API, не захардкожено.
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

    const body: WorkoutSubmitRequest = {
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
    return <p className="screen-message">Загружаю план тренировки…</p>;
  }
  if (state.phase === "error") {
    return (
      <div>
        <p className="screen-message">Не удалось загрузить план: {state.message}</p>
        <Button className="action-button" size="l" stretched onClick={closeMiniApp}>
          Открыть в боте
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
        <Button className="action-button" size="l" stretched onClick={closeMiniApp}>
          Открыть в боте
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
  if (state.phase === "done") {
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
        <Button className="action-button" size="l" stretched onClick={closeMiniApp}>
          Готово
        </Button>
      </div>
    );
  }

  const { plan } = state;
  return (
    <div>
      <p className="plan-title">Текущий план</p>
      {plan.is_gap_rollback && (
        <p className="gap-banner">Был перерыв — цель блока A немного снижена, это нормально.</p>
      )}

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
      <Button className="action-button" size="l" stretched disabled={submitting} onClick={() => void handleSubmit(plan, false)}>
        Записать тренировку
      </Button>
    </div>
  );
}
