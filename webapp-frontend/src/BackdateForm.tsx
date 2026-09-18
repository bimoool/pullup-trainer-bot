import { Button, Input, Placeholder, Section, Select, Spinner } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  fetchBackdatePlan,
  submitBackdate,
  type BackdateSubmitRequest,
  type BandItemInfo,
  type WorkoutPlanResponse,
  type WorkoutSubmitResponse,
} from "./api";
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
  | { phase: "form"; plan: WorkoutPlanResponse }
  | { phase: "anomaly_confirm"; plan: WorkoutPlanResponse; result: WorkoutSubmitResponse }
  | { phase: "done"; result: WorkoutSubmitResponse };

// Бэкдейт по-прежнему не гейтует too_early/gap_retest_required/deload_due
// (issue #52, см. app/web/routes.py::_resolve_backdate_context) — эти статусы
// про готовность к СЛЕДУЮЩЕЙ живой тренировке, не про запись прошлой.
// first_workout/equipment_setup_required — исключение (issue #123): без них
// resolve_next_targets на пустой истории/при ожидающей смене снаряда отдавал
// бы снаряд-заглушку (резину без item_id, взять физически неоткуда), форма
// вела в тупик 400 при попытке сохранить. На практике эта форма уже не
// открывается на этих статусах — WorkoutScreen.tsx прячет саму кнопку входа
// (NO_EQUIPMENT_YET_STATUSES) — сообщения здесь на случай прямого захода.
const STATUS_MESSAGES: Record<string, string> = {
  no_access: "Нет активной подписки. Оформи её в боте, потом возвращайся сюда.",
  no_active_set: "Не получилось открыть тренировочный цикл. Напиши в поддержку через бота.",
  not_onboarded: "Похоже, ты ещё не проходил онбординг — начни его в боте.",
  first_workout: "Это твоя первая тренировка — замер и выбор снаряда пока доступны только в боте.",
  equipment_setup_required: "Нужно заново выбрать снаряд для одного из блоков — сделай это в боте.",
};

export const EQUIPMENT_TYPE_LABELS: { value: string; label: string }[] = [
  { value: "band", label: "Резина" },
  { value: "bodyweight", label: "Свой вес" },
  { value: "weight", label: "Отягощение" },
  { value: "australian", label: "Австралийские" },
];

function todayIsoDate(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

export type EquipmentChoice = { type: string; value: string; bandItemId: string };

/** Явный выбор снаряда (тип + значение/резина) — переиспользуется формой
 * свободных подтягиваний (issue #109, FreeWorkoutScreen.tsx), тот же смысл,
 * что и здесь: снаряд не наследуется из прогрессии, вводится явно. */
export function EquipmentTypeFields({
  letter,
  choice,
  onTypeChange,
  onValueChange,
  onBandItemChange,
  bandItems,
}: {
  letter: "A" | "B";
  choice: EquipmentChoice;
  onTypeChange: (value: string) => void;
  onValueChange: (value: string) => void;
  onBandItemChange: (value: string) => void;
  bandItems: BandItemInfo[];
}) {
  return (
    <>
      <Select
        header="Снаряд"
        aria-label={`Блок ${letter}, снаряд`}
        value={choice.type}
        onChange={(e) => onTypeChange(e.target.value)}
      >
        {EQUIPMENT_TYPE_LABELS.map(({ value, label }) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </Select>

      {choice.type === "weight" && (
        <Input
          header="Вес (кг)"
          after="кг"
          type="number"
          inputMode="decimal"
          min={0}
          step="0.5"
          aria-label={`Блок ${letter}, вес`}
          value={choice.value}
          onChange={(e) => onValueChange(e.target.value)}
        />
      )}

      {choice.type === "band" && (
        <Select
          header="Резина"
          aria-label={`Блок ${letter}, резина`}
          value={choice.bandItemId}
          onChange={(e) => onBandItemChange(e.target.value)}
        >
          <option value="">Выбери резину</option>
          {bandItems.map((item) => (
            <option key={item.id} value={item.id}>
              {item.name}
              {item.resistance_kg !== null ? ` (${item.resistance_kg} кг)` : ""}
            </option>
          ))}
        </Select>
      )}
    </>
  );
}

/**
 * Форма "Внести пропущенную тренировку" (issue #52) — снаряд здесь ВСЕГДА
 * явный выбор (тип + значение/резина), в отличие от WorkoutScreen.tsx, где
 * снаряд наследуется молча из прогрессии: тот же принцип, что явный
 * переспрос снаряда у бота для бэкдейта (app/bot/handlers/backdate.py,
 * _begin_equipment_setup(target_a_state=None, ...)). Единственная проверка
 * даты — "не в будущем" (<input type="date" max={сегодня}>) — календарь
 * бота здесь не переносится 1-в-1 (issue сам разрешает упростить для веба),
 * лимита на глубину бэкдейта в реальном коде бота нет.
 *
 * `Placeholder`/`Spinner` вместо `.screen-message` для loading/error/
 * not_ready (issue #142) — тот же базовый паттерн, что AchievementsScreen.tsx.
 * `SetInputGrid`/`.block-section`/`.anomaly-card`/`.done-card`/остальная
 * разметка блоков не тронуты — общий визуальный язык с `WorkoutScreen.tsx`
 * (PR 6 по плану, ещё не мигрирован), см. тот же вывод в HistoryEditForm.tsx.
 */
export function BackdateForm({ initDataRaw, onDone, onCancel }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });
  const [performedAt, setPerformedAt] = useState(todayIsoDate());
  const [blockAWorking, setBlockAWorking] = useState<string[]>([]);
  const [blockAMax, setBlockAMax] = useState("");
  const [blockBWorking, setBlockBWorking] = useState<string[]>([]);
  const [blockBMax, setBlockBMax] = useState("");
  const [blockAEquipment, setBlockAEquipment] = useState<EquipmentChoice>({ type: "bodyweight", value: "", bandItemId: "" });
  const [blockBEquipment, setBlockBEquipment] = useState<EquipmentChoice>({ type: "bodyweight", value: "", bandItemId: "" });
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
    const workingA = parseSetValues(blockAWorking);
    const maxA = parseSetValue(blockAMax);
    const workingB = parseSetValues(blockBWorking);
    const maxB = parseSetValue(blockBMax);
    if (workingA === null || maxA === null || workingB === null || maxB === null) {
      setFormError("Заполни все подходы числами — пустые или нечисловые поля недопустимы.");
      return;
    }
    if (blockAEquipment.type === "weight" && !(Number(blockAEquipment.value) > 0)) {
      setFormError("Укажи вес для блока A.");
      return;
    }
    if (blockBEquipment.type === "weight" && !(Number(blockBEquipment.value) > 0)) {
      setFormError("Укажи вес для блока Б.");
      return;
    }
    if (blockAEquipment.type === "band" && !blockAEquipment.bandItemId) {
      setFormError("Выбери резину для блока A.");
      return;
    }
    if (blockBEquipment.type === "band" && !blockBEquipment.bandItemId) {
      setFormError("Выбери резину для блока Б.");
      return;
    }
    setFormError(null);

    const body: BackdateSubmitRequest = {
      performed_at: performedAt,
      block_a_working_reps: workingA,
      block_a_max_reps: maxA,
      block_b_working_reps: workingB,
      block_b_max_reps: maxB,
      block_a_equipment_type: blockAEquipment.type,
      block_a_equipment_value: blockAEquipment.type === "weight" ? blockAEquipment.value : null,
      block_a_equipment_item_id: blockAEquipment.type === "band" ? Number(blockAEquipment.bandItemId) : null,
      block_b_equipment_type: blockBEquipment.type,
      block_b_equipment_value: blockBEquipment.type === "weight" ? blockBEquipment.value : null,
      block_b_equipment_item_id: blockBEquipment.type === "band" ? Number(blockBEquipment.bandItemId) : null,
      confirm_anomalies: confirmAnomalies,
    };

    setSubmitting(true);
    try {
      const result = await submitBackdate(initDataRaw, body);
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
      <p className="plan-title">Внести пропущенную тренировку</p>

      <Input
        header="Дата"
        type="date"
        max={todayIsoDate()}
        aria-label="Дата тренировки"
        value={performedAt}
        onChange={(e) => setPerformedAt(e.target.value)}
      />

      <Section className="block-section" header="Блок A — объём">
        <span className="field-label">Рабочие подходы</span>
        <SetInputGrid
          values={blockAWorking}
          onChangeAt={(index, value) => setBlockAWorking((prev) => replaceAt(prev, index, value))}
          ariaLabelPrefix="Блок A, подход"
        />
        <span className="field-label">Подход на максимум</span>
        <div className="set-grid">
          <input
            className="set-input max-input"
            type="number"
            inputMode="numeric"
            min={0}
            max={999}
            aria-label="Блок A, подход на максимум"
            value={blockAMax}
            onChange={(e) => setBlockAMax(e.target.value)}
          />
        </div>
        <EquipmentTypeFields
          letter="A"
          choice={blockAEquipment}
          onTypeChange={(value) => setBlockAEquipment({ type: value, value: "", bandItemId: "" })}
          onValueChange={(value) => setBlockAEquipment((prev) => ({ ...prev, value }))}
          onBandItemChange={(value) => setBlockAEquipment((prev) => ({ ...prev, bandItemId: value }))}
          bandItems={plan.band_items}
        />
      </Section>

      <Section className="block-section" header="Блок Б — сила">
        <span className="field-label">Рабочие подходы</span>
        <SetInputGrid
          values={blockBWorking}
          onChangeAt={(index, value) => setBlockBWorking((prev) => replaceAt(prev, index, value))}
          ariaLabelPrefix="Блок Б, подход"
        />
        <span className="field-label">Подход на максимум</span>
        <div className="set-grid">
          <input
            className="set-input max-input"
            type="number"
            inputMode="numeric"
            min={0}
            max={999}
            aria-label="Блок Б, подход на максимум"
            value={blockBMax}
            onChange={(e) => setBlockBMax(e.target.value)}
          />
        </div>
        <EquipmentTypeFields
          letter="B"
          choice={blockBEquipment}
          onTypeChange={(value) => setBlockBEquipment({ type: value, value: "", bandItemId: "" })}
          onValueChange={(value) => setBlockBEquipment((prev) => ({ ...prev, value }))}
          onBandItemChange={(value) => setBlockBEquipment((prev) => ({ ...prev, bandItemId: value }))}
          bandItems={plan.band_items}
        />
      </Section>

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
