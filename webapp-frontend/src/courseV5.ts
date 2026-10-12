/**
 * Программа «Подтягивания» V5.6 (issue #305) — чистые функции отображения поверх рецепта из снимка сессии
 * (`course_program` / `course_block` / маркеры подходов). Логика программы — только на сервере
 * (app/domain/pullups_v5.py); здесь — тексты и сборка подтверждений пользователя. Движок #306 исполняет
 * отдых/стоп-правила рецепта; этот модуль их не изображает.
 */

export type CourseSetMarker = "working" | "amrap" | "control" | "dynamic";

export interface CourseSetTarget {
  value: string;
  marker?: string | null;
  cap_reps?: number | null;
}

/** Подпись цели подхода по маркеру V5.6; null — не подход V5.6 (обычная подпись). */
export function courseTargetText(target: CourseSetTarget | null | undefined): string | null {
  if (!target || !target.marker) {
    return null;
  }
  const reps = Number(target.value);
  switch (target.marker) {
    case "amrap":
      return `Максимум чистых, не меньше ${reps}`;
    case "control":
      return `Цель: ${reps}–${target.cap_reps ?? reps}, не больше ${target.cap_reps ?? reps}`;
    case "dynamic":
      return `Цель: ${reps}; 2 и меньше — блок окончен`;
    case "working":
      return `Цель: ${reps}`;
    default:
      return null;
  }
}

export interface BlockCheck {
  block_index: number;
  technique_valid: boolean | null;
  rest_within_limit: boolean | null;
}

/** Подтверждения по блокам для `…/complete`. Неотмеченное — null («неизвестно»), не false и не true:
 * сервер неизвестное валидным не считает. */
export function blockChecks(flags: { technique: boolean; rest: boolean }[]): BlockCheck[] {
  return flags.map((flag, index) => ({
    block_index: index,
    technique_valid: flag.technique ? true : null,
    rest_within_limit: flag.rest ? true : null,
  }));
}

export interface CourseBlockOutcome {
  block_role: string;
  decision: string;
  reason?: string | null;
  fact_volume?: number | null;
  details?: Record<string, unknown>;
}

const BLOCK_LABEL: Record<string, string> = {
  a_volume: "Объём A",
  b_volume: "Объём B",
  assisted_strength: "Сила с помощью",
  a_weighted_strength: "Сила A (5×5)",
  b_weighted_strength: "Сила B (5×3)",
};

const DECISION_TEXT: Record<string, string> = {
  add_mandatory_rep: "+1 обязательное повторение в следующей A",
  repeat: "план повторяется",
  rollback_last_addition: "откат последнего добавленного повторения",
  increase_assistance: "нужна помощь сильнее",
  advance: "следующая ступень",
  hold: "ступень повторяется",
  decrease_assistance: "помощь меньше на одну ступень",
  keep_assistance: "помощь та же",
  qualify: "допуск к работе с весом",
  increase_load: "вес растёт",
  calibrate_undo_last_increase: "отмена последней прибавки веса",
  offer_fresh_1rm_or_recalibrate: "можно пройти новый 1RM или откалиброваться снизу",
};

const REASON_TEXT: Record<string, string> = {
  unconfirmed: "техника не подтверждена",
  standard_unconfirmed: "техника или отдых не подтверждены",
  technique_unconfirmed: "техника не подтверждена",
  rest_unconfirmed: "отдых не подтверждён",
  plan_not_closed: "план не закрыт",
  assistance_confirmation_required: "подтвердите следующую резину целиком (модель, цвет, крепление, положение)",
  recovery_check_required: "сначала проверка восстановления",
  load_increment_unavailable: "нет доступного шага веса",
};

/** Строка итога блока: «Сила A (5×5): вес растёт (+1.5 кг)». */
export function describeCourseOutcome(outcome: CourseBlockOutcome): string {
  const label = BLOCK_LABEL[outcome.block_role] ?? outcome.block_role;
  let text = DECISION_TEXT[outcome.decision] ?? outcome.decision;
  const delta = outcome.details?.["delta_kg"];
  if (outcome.decision === "increase_load" && typeof delta === "string") {
    text += ` (+${delta} кг)`;
  }
  const goal = outcome.details?.["intermediate_goal"];
  if (outcome.block_role === "b_volume" && outcome.decision === "hold" && typeof goal === "number") {
    text += `; в следующий раз — не меньше ${goal}`;
  }
  const reason = outcome.reason ? REASON_TEXT[outcome.reason] : undefined;
  return reason ? `${label}: ${text} — ${reason}` : `${label}: ${text}`;
}

const PENDING_TEXT: Record<string, string> = {
  fresh_max: "свежий максимум подтягиваний",
  volume_capacity: "сколько повторений с объёмной резиной (≈8–12)",
  volume_assistance: "объёмная резина",
  strength_assistance: "помощь в силовом блоке",
  body_mass: "масса тела",
  one_rep_max: "тест 1RM (или ваш недавний результат 5×5 / 5×3)",
  load_step: "шаг дополнительного веса",
  volume_reference: "объём первой тренировки A",
  assistance_confirmation: "подтверждение следующей резины (модель, цвет, крепление, положение)",
};

export function describePendingInputs(missing: string[]): string {
  return missing.map((item) => PENDING_TEXT[item] ?? item).join(", ");
}

/** Поля формы входов V5.6 — какие показать для списка недостающих входов (порядок — порядок формы). */
export const COURSE_INPUT_FIELDS: Record<string, { key: string; label: string; unit?: string }[]> = {
  fresh_max: [{ key: "fresh_max", label: "Свежий максимум строгих подтягиваний", unit: "повт." }],
  volume_capacity: [{ key: "volume_capacity", label: "Строгих повторений с объёмной резиной (≈8–12)", unit: "повт." }],
  body_mass: [{ key: "body_mass_kg", label: "Масса тела", unit: "кг" }],
  one_rep_max: [
    // E1RM вручную не вводится: он — только результат теста 1RM в приложении (OneRepMaxTest, сервер проверяет
    // лестницу). Альтернатива — недавний результат 5×5 / 5×3 со слов пользователя (V5.6 §8; сервер его не сверяет).
    { key: "known_strength_a_kg", label: "Или: вы недавно закрыли 5×5 (сила A) в том же стандарте и месте, после объёма — доп. вес", unit: "кг" },
    { key: "known_strength_b_kg", label: "Или: вы недавно закрыли 5×3 (сила B) в том же стандарте и месте, после объёма — доп. вес", unit: "кг" },
  ],
  load_step: [{ key: "load_step_kg", label: "Шаг дополнительного веса (самый маленький диск)", unit: "кг" }],
};

export interface BandFields {
  bodyweight: boolean;
  name: string;
  colour: string;
  attachment: string;
  body_position: string;
}

export function bandComplete(fields: BandFields): boolean {
  return fields.bodyweight || [fields.name, fields.colour, fields.attachment, fields.body_position].every((v) => v.trim() !== "");
}

/** Подтверждения смены помощи: только полностью заполненные записи (или «без помощи»). */
export function assistanceConfirmations(
  entries: { block: string; fields: BandFields }[],
): { block: string; setup: Record<string, unknown> }[] {
  return entries.filter((entry) => bandComplete(entry.fields)).map(({ block, fields }) => ({
    block,
    setup: fields.bodyweight
      ? { kind: "bodyweight" }
      : {
        kind: "band", name: fields.name.trim(), colour: fields.colour.trim(), attachment: fields.attachment.trim(),
        body_position: fields.body_position.trim(),
      },
  }));
}

/** Тело PUT …/course/inputs из значений формы: пустые поля не шлём (не угадываем значения). */
export function courseInputsPayload(
  numbers: Record<string, string>, bands: { volume?: BandFields; strength?: BandFields }, recoveryChecked: boolean,
): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const [key, raw] of Object.entries(numbers)) {
    const value = raw.trim().replace(",", ".");
    if (value !== "") {
      body[key] = key === "fresh_max" || key === "volume_capacity" ? Number.parseInt(value, 10) : value;
    }
  }
  const band = (fields: BandFields | undefined): Record<string, unknown> | null => {
    if (!fields) {
      return null;
    }
    if (fields.bodyweight) {
      return { kind: "bodyweight" };
    }
    // Резина готова к использованию только целиком: модель/название, цвет, крепление, положение (V5.6 §8.2).
    if (!bandComplete(fields)) {
      return null;
    }
    return {
      kind: "band", name: fields.name.trim(), colour: fields.colour.trim() || null,
      attachment: fields.attachment.trim() || null, body_position: fields.body_position.trim() || null,
    };
  };
  const volume = band(bands.volume);
  if (volume) {
    body.volume_assistance = volume;
  }
  const strength = band(bands.strength);
  if (strength) {
    body.strength_assistance = strength;
  }
  if (recoveryChecked) {
    body.clear_recovery_check = true;
  }
  return body;
}
