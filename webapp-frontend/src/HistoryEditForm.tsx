import { Button, Input, Section } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  fetchHistoryDetail,
  patchHistoryEdit,
  type HistoryEditDetail,
  type HistoryEditRequest,
  type WorkoutSubmitResponse,
} from "./api";
import {
  AnomalyLines,
  BlockForm,
  EquipmentCorrectionFields,
  parseOptionalWeight,
  parseSetValue,
  parseSetValues,
  replaceAt,
} from "./WorkoutScreen";

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
  | { phase: "done"; result: WorkoutSubmitResponse; isFreeEntry: boolean };

/** "2026-09-03" -> "03.09.2026" — тот же формат, что HistoryScreen.tsx. */
function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split("-");
  return `${day}.${month}.${year}`;
}

/** Тот же формат "только итог" (issue #88/#147), но для блока A — тот же
 * принцип: working_reps пуст означает запись сделана без раскладки по
 * подходам, независимо от того, заполнен ли reported_volume явно (легаси-
 * записи до фикса issue #88 хранят введённое число в max_reps напрямую).
 * См. докстринг isTotalFormatB ниже — тут ровно то же самое, для блока A. */
function isTotalFormatA(detail: HistoryEditDetail): boolean {
  return detail.block_a.working_reps.length === 0;
}

/** working_reps пуст — запись блока Б создана в режиме "только итог" (issue
 * #88), без раскладки по подходам. Проверяем именно это, не
 * `reported_volume !== null` — записи, созданные ДО фикса issue #88, тоже
 * хранят working_reps=[] (пустая раскладка), но при этом reported_volume
 * ещё не существовало как поля и осталось null, а введённое пользователем
 * число легло в max_reps напрямую (сам баг issue #88). Раскладка по
 * подходам (обычная/бэкдейт-запись) физически не может быть пустой —
 * блок Б требует минимум один рабочий подход везде, где формат "только
 * итог" не выбран явно, поэтому working_reps.length === 0 однозначно
 * определяет оба варианта формата "только итог" (issue #147). Форма
 * должна остаться в том же формате при правке (issue #106) —
 * переключения формата нет. */
function isTotalFormatB(detail: HistoryEditDetail): boolean {
  return detail.block_b.working_reps.length === 0;
}

/**
 * Форма редактирования прошлой тренировки (issue #52, расширено issue
 * #106 на бэкдейт/свободные записи) — та же разметка блоков, что
 * WorkoutScreen.tsx (BlockForm/AnomalyLines/парсинг оттуда же, не копия),
 * предзаполненная реально введёнными числами из GET /api/history/{id},
 * сабмит через PATCH /api/history/{id} (app.web.routes::edit_history_workout).
 * Тренировки цепочки каскада правятся с пересчётом (edit_workout), внесённые
 * не в цепочку (бэкдейт/свободные) — без пересчёта цели/каскада
 * (edit_noncascade_workout), форма одна и та же, ветвление на бэкенде.
 *
 * Блок Б в формате "только итог" (issue #88) показывает не сетку подходов,
 * а поле итога + опциональный максимум — тот же формат, в котором запись
 * была создана в боте (app.bot.handlers.backdate.py), без переключения.
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
  const [blockATotal, setBlockATotal] = useState("");
  const [blockATotalMax, setBlockATotalMax] = useState("");
  const [blockBWorking, setBlockBWorking] = useState<string[]>([]);
  const [blockBMax, setBlockBMax] = useState("");
  const [blockBTotal, setBlockBTotal] = useState("");
  const [blockBTotalMax, setBlockBTotalMax] = useState("");
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
          setState({ phase: "error", message: "Эта тренировка не редактируется." });
          return;
        }
        if (isTotalFormatA(detail)) {
          if (detail.block_a.reported_volume !== null) {
            setBlockATotal(String(detail.block_a.reported_volume));
            setBlockATotalMax(detail.block_a.max_reps > 0 ? String(detail.block_a.max_reps) : "");
          } else {
            // Легаси-запись до фикса issue #88 — та же логика, что и у
            // блока Б ниже: введённое число лежит в max_reps.
            setBlockATotal(String(detail.block_a.max_reps));
            setBlockATotalMax("");
          }
        } else {
          setBlockAWorking(detail.block_a.working_reps.map(String));
          setBlockAMax(String(detail.block_a.max_reps));
        }
        if (isTotalFormatB(detail)) {
          if (detail.block_b.reported_volume !== null) {
            setBlockBTotal(String(detail.block_b.reported_volume));
            setBlockBTotalMax(detail.block_b.max_reps > 0 ? String(detail.block_b.max_reps) : "");
          } else {
            // Легаси-запись до фикса issue #88 — введённое число лежит в
            // max_reps (см. isTotalFormatB выше), сам факт "это был честный
            // отдельный подход на максимум" не зафиксирован достоверно,
            // поэтому "лучший подход" оставляем пустым, а не равным итогу.
            setBlockBTotal(String(detail.block_b.max_reps));
            setBlockBTotalMax("");
          }
        } else {
          setBlockBWorking(detail.block_b.working_reps.map(String));
          setBlockBMax(String(detail.block_b.max_reps));
        }
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
    const totalFormatA = isTotalFormatA(detail);
    let workingA: number[] = [];
    let maxA = 0;
    let reportedVolumeA: number | null = null;
    if (totalFormatA) {
      const total = parseSetValue(blockATotal);
      if (total === null) {
        setFormError("Итог блока А должен быть числом.");
        return;
      }
      const maxOrSkip = blockATotalMax.trim() === "" ? 0 : parseSetValue(blockATotalMax);
      if (maxOrSkip === null) {
        setFormError("Максимум блока А должен быть числом, если он указан.");
        return;
      }
      reportedVolumeA = total;
      maxA = maxOrSkip;
    } else {
      const working = parseSetValues(blockAWorking);
      const max = parseSetValue(blockAMax);
      if (working === null || max === null) {
        setFormError("Заполни все подходы блока А числами — пустые или нечисловые поля недопустимы.");
        return;
      }
      workingA = working;
      maxA = max;
    }

    const totalFormatB = isTotalFormatB(detail);
    let workingB: number[] = [];
    let maxB = 0;
    let reportedVolumeB: number | null = null;
    if (detail.is_free_entry) {
      // Свободные подтягивания (issue #109) — блок Б технически существует
      // в БД как нулевой (working_reps=[], max_reps=0, см.
      // WorkoutRepository.record_free_workout), но по смыслу отсутствует —
      // не показываем его и не валидируем, просто отправляем то же самое
      // нулевое значение обратно, без изменений.
      reportedVolumeB = 0;
    } else if (totalFormatB) {
      const total = parseSetValue(blockBTotal);
      if (total === null) {
        setFormError("Итог блока Б должен быть числом.");
        return;
      }
      // Пустое поле максимума — он не был зафиксирован (тот же смысл, что
      // "Пропустить" у app.bot.handlers.backdate.py::handle_backdate_block_b_total_max_skip).
      const maxOrSkip = blockBTotalMax.trim() === "" ? 0 : parseSetValue(blockBTotalMax);
      if (maxOrSkip === null) {
        setFormError("Максимум блока Б должен быть числом, если он указан.");
        return;
      }
      reportedVolumeB = total;
      maxB = maxOrSkip;
    } else {
      const working = parseSetValues(blockBWorking);
      const max = parseSetValue(blockBMax);
      if (working === null || max === null) {
        setFormError("Заполни все подходы блока Б числами — пустые или нечисловые поля недопустимы.");
        return;
      }
      workingB = working;
      maxB = max;
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
      block_a_reported_volume: reportedVolumeA,
      block_b_working_reps: workingB,
      block_b_max_reps: maxB,
      block_b_reported_volume: reportedVolumeB,
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
      setState({ phase: "done", result, isFreeEntry: detail.is_free_entry });
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
          {!state.isFreeEntry && <p>Блок B: {result.result_b}</p>}
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

      {isTotalFormatA(detail) ? (
        <Section className="block-section" header={`Блок A — цель ${detail.block_a.target_before}`}>
          <div className="block-header">
            <div className="block-badge">A</div>
            <p className="block-subtitle">
              Итог за тренировку, без раскладки по подходам · {detail.block_a.equipment.label}
            </p>
          </div>

          <Input
            header="Итог за тренировку"
            type="number"
            inputMode="numeric"
            min={0}
            max={999}
            aria-label="Блок А, итог за тренировку"
            value={blockATotal}
            onChange={(e) => setBlockATotal(e.target.value)}
          />
          <Input
            header="Лучший подход (максимум), если он известен"
            type="number"
            inputMode="numeric"
            min={0}
            max={999}
            aria-label="Блок А, лучший подход"
            value={blockATotalMax}
            onChange={(e) => setBlockATotalMax(e.target.value)}
          />

          <EquipmentCorrectionFields
            letter="A"
            equipmentType={detail.block_a.equipment.type}
            equipmentLabel={detail.block_a.equipment.label}
            actualWeightValue={blockAActualWeight}
            onActualWeightChange={setBlockAActualWeight}
            bandItems={[]}
            bandItemValue=""
            onBandItemChange={() => {}}
          />
        </Section>
      ) : (
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
      )}

      {detail.is_free_entry ? null : isTotalFormatB(detail) ? (
        <Section className="block-section" header={`Блок Б — цель ${detail.block_b.target_before}`}>
          <div className="block-header">
            <div className="block-badge">B</div>
            <p className="block-subtitle">
              Итог за тренировку, без раскладки по подходам · {detail.block_b.equipment.label}
            </p>
          </div>

          <Input
            header="Итог за тренировку"
            type="number"
            inputMode="numeric"
            min={0}
            max={999}
            aria-label="Блок Б, итог за тренировку"
            value={blockBTotal}
            onChange={(e) => setBlockBTotal(e.target.value)}
          />
          <Input
            header="Лучший подход (максимум), если он известен"
            type="number"
            inputMode="numeric"
            min={0}
            max={999}
            aria-label="Блок Б, лучший подход"
            value={blockBTotalMax}
            onChange={(e) => setBlockBTotalMax(e.target.value)}
          />

          <EquipmentCorrectionFields
            letter="B"
            equipmentType={detail.block_b.equipment.type}
            equipmentLabel={detail.block_b.equipment.label}
            actualWeightValue={blockBActualWeight}
            onActualWeightChange={setBlockBActualWeight}
            bandItems={[]}
            bandItemValue=""
            onBandItemChange={() => {}}
          />
        </Section>
      ) : (
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
      )}

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
