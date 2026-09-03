import { Input, Section, Select } from "@telegram-apps/telegram-ui";

import type { AnomalyFlags, BandItemInfo } from "./api";

/** Общая разметка/парсинг блока ввода повторений (issue #52, волна 2) —
 * вынесено из WorkoutScreen.tsx, чтобы формы редактирования истории
 * (HistoryEditForm) и внесения задним числом (BackdateForm) переиспользовали
 * тот же код, а не копировали его: та же форма ввода, что уже есть для живой
 * тренировки, просто предзаполненная/без предложенной цели-обязательства. */

/** Каждое поле — один подход, без разделителей и ручного парсинга строки. */
export function parseSetValue(raw: string): number | null {
  const trimmed = raw.trim();
  if (!/^\d+$/.test(trimmed)) {
    return null;
  }
  return Number(trimmed);
}

export function parseSetValues(values: string[]): number[] | null {
  if (values.length === 0) {
    return null;
  }
  const parsed = values.map(parseSetValue);
  if (parsed.some((n) => n === null)) {
    return null;
  }
  return parsed as number[];
}

export function replaceAt(values: string[], index: number, value: string): string[] {
  return values.map((v, i) => (i === index ? value : v));
}

/** Пустое поле — правки нет (null, сервер оставит вес из прогрессии как
 * есть); непустое — должно быть положительным числом, как и живой ввод
 * веса в боте (app/bot/handlers/equipment.py::handle_equipment_value). */
export function parseOptionalWeight(raw: string): { ok: true; value: string | null } | { ok: false } {
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

export function AnomalyLines({ flags }: { flags: AnomalyFlags }) {
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

export function BlockForm({
  letter,
  target,
  targetLabel,
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
  /** "цель"/"цель до этой тренировки" — разный смысл у формы живой
   * тренировки (следующая цель) и формы редактирования (target_before
   * отредактированной записи), см. вызовы. */
  targetLabel?: string;
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
    <Section className="block-section" header={`Блок ${letter} — ${targetLabel ?? "цель"} ${target}`}>
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
          app/web/routes.py — сервер игнорирует поле для остальных типов),
          поле здесь просто не показывается. */}
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
