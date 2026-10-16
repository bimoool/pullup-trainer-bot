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

/** Название блока основного занятия V5.6 по порядку блока в сессии — из замороженного рецепта сессии
 * (`prescription_snapshot.provenance.course_program.blocks[i].block_role`): «Объём A», «Сила A (5×5)».
 * null — снимка/роли нет (не V5.6, старая сессия): подпись не выдумываем. */
export function courseBlockName(snapshot: Record<string, unknown> | null | undefined, blockIndex: number): string | null {
  const provenance = snapshot?.["provenance"];
  const program = provenance !== null && typeof provenance === "object"
    ? (provenance as Record<string, unknown>)["course_program"] : null;
  const blocks = program !== null && typeof program === "object" ? (program as Record<string, unknown>)["blocks"] : null;
  if (!Array.isArray(blocks)) {
    return null;
  }
  const block = blocks[blockIndex];
  const role = block !== null && typeof block === "object" ? (block as Record<string, unknown>)["block_role"] : null;
  return typeof role === "string" ? BLOCK_LABEL[role] ?? null : null;
}

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
  body_mass: "ваш вес (масса тела)",
  one_rep_max: "тест 1RM (или ваш недавний результат 5×5 / 5×3)",
  load_step: "шаг дополнительного веса",
  volume_reference: "объём первой тренировки A",
  assistance_confirmation: "подтверждение следующей резины (модель, цвет, крепление, положение)",
};

export function describePendingInputs(missing: string[]): string {
  return missing.map((item) => PENDING_TEXT[item] ?? item).join(", ");
}

/** Без массы тела и шага веса лестницу 1RM не построить: сервер отвечает 409 course_setup_required (V5.6 §10). */
export const ONE_RM_REQUIRED_INPUTS: { item: string; key: string }[] = [
  { item: "body_mass", key: "body_mass_kg" }, { item: "load_step", key: "load_step_kg" },
];

/** V5.6 §9: прибавка веса — ближайший шаг в пределах 0,5–2,5 кг; шаг больше 2,5 кг прибавок не даст. */
export const LOAD_STEP_MAX_INCREMENT_KG = 2.5;

export function loadStepWarning(raw: string): string | null {
  const value = Number(raw.trim().replace(",", "."));
  if (!Number.isFinite(value) || value <= LOAD_STEP_MAX_INCREMENT_KG) {
    return null;
  }
  return "Шаг больше 2,5 кг: программа прибавляет вес шагами от 0,5 до 2,5 кг, с таким шагом прибавок веса не будет. "
    + "Шаг — это самый маленький диск или гантель, на который можно увеличить вес, а не масса тела и не вес отягощения.";
}

/** Текст ошибки курса для экрана: недостающие входы — по-русски, а не адресом запроса. */
export function describeCourseError(error: unknown, action = "продолжить"): string {
  const coded = error as { code?: unknown; missing?: unknown; message?: unknown } | null;
  if (coded && coded.code === "course_setup_required" && Array.isArray(coded.missing) && coded.missing.length > 0) {
    return `Чтобы ${action}, не хватает: ${describePendingInputs(coded.missing as string[])}. Заполните поле выше.`;
  }
  return error instanceof Error ? error.message : String(error);
}

/**
 * Зачем программе помощь/вес — по ПРАВИЛАМ ДОПУСКА V5.6 (§8.2, docs/domain/PULLUPS_V5_6.md), а не по придуманным
 * порогам: свежий максимум M < 10 — уровень 1, объём и сила начинаются с помощью (резина); M ≥ 10 — допуск к
 * работе с весом (сила считается от 1RM или недавнего 5×5 / 5×3). Конкретную резину и килограммы приложение не
 * назначает: резину пользователь записывает целиком (модель, цвет, крепление, положение), вес даёт тест или его
 * собственный недавний результат. Пустой список — объяснять нечего (в форме нет входов про помощь/вес).
 */
export function describeSetupNeeds(
  missing: string[], assistancePending: { block: string; intent: string }[] = [],
): string[] {
  const lines: string[] = [];
  if (missing.includes("volume_assistance") || missing.includes("strength_assistance")) {
    lines.push(
      "Свежий максимум строгих подтягиваний пока меньше 10 — по правилам допуска программа начинается с помощью: "
      + "резина в объёмных подходах и в силовом блоке. Допуск к работе с весом откроется, когда сила пройдёт "
      + "5/5/5/5/8 без помощи или свежий максимум достигнет 10.",
    );
    lines.push(
      "Укажите ту резину, которой вы реально пользуетесь: приложение не подбирает ни резину, ни её усилие. "
      + "Запись принимается целиком — модель, цвет, крепление и положение стопы/колена; подтверждается кнопкой «Сохранить».",
    );
  }
  if (missing.includes("one_rep_max")) {
    lines.push(
      "Допуск к работе с весом получен (свежий максимум 10 и больше или сила без помощи 5/5/5/5/8) — сила считается "
      + "с дополнительным весом. Вес не назначается "
      + "наугад: его даёт тест 1RM в приложении или ваш недавний результат 5×5 / 5×3 в том же стандарте и месте.",
    );
  }
  if (missing.includes("load_step")) {
    lines.push("Шаг веса нужен, чтобы округлять нагрузку вниз до реального диска; приложение его не подставляет.");
  }
  for (const entry of assistancePending) {
    lines.push(
      entry.intent === "decrease_assistance"
        ? "По правилам ступеней помощи прошлое занятие позволяет уменьшить помощь — выберите следующую резину и "
          + "подтвердите её запись целиком; пока не подтверждено, прежняя помощь сохраняется."
        : "По правилам ступеней помощи прошлое занятие просит больше помощи — выберите следующую резину и "
          + "подтвердите её запись целиком; пока не подтверждено, прежняя помощь сохраняется.",
    );
  }
  return [...new Set(lines)];
}

/**
 * Что замер означает для помощи/веса — по ТЕМ ЖЕ правилам допуска, что `initial_state` (app/domain/pullups_v5.py §8.2,
 * порог QUALIFY_FRESH_MAX = 10, STANDARD_VOLUME_FROM_FRESH_MAX = 15), показывается сразу после замера в онбординге.
 * Только объяснение и следующий шаг к существующему setup курса: резину, килограммы и рецепт приложение не назначает
 * (рецепт считает сервер от входов, их вводят на экране входов курса).
 */
export interface BaselineQualification {
  headline: string;
  lines: string[];
  nextStep: string;
}

export function describeBaselineQualification(reps: number): BaselineQualification {
  const nextStep =
    "Дальше: после анкеты откройте на Главной курс «Подтягивания» → «Добавить в план» → «Начать». "
    + "На первом старте программа попросит недостающие данные; всё, что вы запишете, остаётся вашим выбором — "
    + "приложение само ничего не назначает.";
  if (reps < 10) {
    return {
      headline: `Замер ${reps}: программа начнётся с помощью`,
      lines: [
        "Меньше 10 строгих подтягиваний — по правилам допуска объём и сила стартуют с помощью, то есть с резиной. "
        + "Допуск к работе с дополнительным весом откроется, когда сила пройдёт 5/5/5/5/8 без помощи или свежий максимум "
        + "достигнет 10.",
        "Вам понадобится резина, которой вы реально пользуетесь: на экране курса её нужно будет записать целиком "
        + "(модель, цвет, крепление, положение).",
      ],
      nextStep,
    };
  }
  if (reps < 15) {
    return {
      headline: `Замер ${reps}: допуск к работе с весом есть, начнётся переходная неделя`,
      lines: [
        "10–14 строгих подтягиваний — объём идёт на собственном весе, а силовой блок считается с дополнительным "
        + "весом: допуск получен.",
        "Вес не назначается наугад: его даёт тест 1RM в приложении или ваш недавний результат 5×5 / 5×3 в том же "
        + "стандарте и месте. Понадобится возможность добавить вес (пояс, гантель) и знать шаг своих дисков.",
      ],
      nextStep,
    };
  }
  return {
    headline: `Замер ${reps}: сразу уровень с дополнительным весом`,
    lines: [
      "15 и больше строгих подтягиваний — объём идёт на собственном весе, сила — с дополнительным весом.",
      "Вес не назначается наугад: его даёт тест 1RM в приложении или ваш недавний результат 5×5 / 5×3. "
      + "Понадобится возможность добавить вес (пояс, гантель) и знать шаг своих дисков.",
    ],
    nextStep,
  };
}

/**
 * Поля формы входов V5.6 — какие показать для списка недостающих входов (порядок — порядок формы). `hint` — что
 * именно вписать, с примером: первый обычный пользователь вписал в шаг веса 16 (принял его за массу тела / вес на
 * поясе), а «Или: 5×5…» стояло раньше самого теста, альтернативой которому оно было.
 */
export const COURSE_INPUT_FIELDS: Record<string, { key: string; label: string; unit?: string; hint?: string }[]> = {
  fresh_max: [{ key: "fresh_max", label: "Свежий максимум строгих подтягиваний", unit: "повт." }],
  volume_capacity: [{ key: "volume_capacity", label: "Строгих повторений с объёмной резиной (≈8–12)", unit: "повт." }],
  body_mass: [{
    key: "body_mass_kg", label: "Ваш вес (масса тела)", unit: "кг",
    hint: "Обязательно. Тот же вес, что в анкете («Твой вес в кг?»), например 78.",
  }],
  one_rep_max: [
    // E1RM вручную не вводится: он — только результат теста 1RM в приложении (OneRepMaxTest, сервер проверяет
    // лестницу). Альтернатива — недавний результат 5×5 / 5×3 со слов пользователя (V5.6 §8; сервер его не сверяет).
    {
      key: "known_strength_a_kg", label: "Недавний 5×5 (сила A): дополнительный вес", unit: "кг",
      hint: "Только вес на поясе или в руках сверх своего веса, не масса тела: закрыли 5×5 с +10 кг — впишите 10. "
        + "Тот же стандарт и место, после объёма.",
    },
    {
      key: "known_strength_b_kg", label: "Недавний 5×3 (сила B): дополнительный вес", unit: "кг",
      hint: "Так же: закрыли 5×3 с +12,5 кг — впишите 12,5.",
    },
  ],
  load_step: [{
    key: "load_step_kg", label: "Шаг дополнительного веса", unit: "кг",
    hint: "Обязательно. Самый маленький диск или гантель, на который вы можете увеличить вес на поясе, — обычно 1,25 "
      + "или 2,5. Это не ваш вес и не вес на поясе.",
  }],
};

/** Подсказка к «Твой вес в кг?» в анкете: та же величина, что «Ваш вес (масса тела)» на экране входов курса. */
export const ONBOARDING_WEIGHT_HINT =
  "Это масса тела, без отягощения. По ней программа «Подтягивания» считает вес в силовых подходах.";

/**
 * Раскладка формы входов: «Данные» (вес, шаг и т. п.) идут сразу перед тестом 1RM — тесту без них не начаться;
 * недавний 5×5 / 5×3 — отдельный вариант ПОСЛЕ теста, а не поля «Или: …» до него.
 */
export function courseSetupLayout(missing: string[]): { dataKeys: string[]; alternativeKeys: string[] } {
  const dataKeys = missing.filter((item) => item !== "one_rep_max")
    .flatMap((item) => (COURSE_INPUT_FIELDS[item] ?? []).map((field) => field.key));
  const alternativeKeys = missing.includes("one_rep_max") ? COURSE_INPUT_FIELDS.one_rep_max.map((field) => field.key) : [];
  return { dataKeys, alternativeKeys };
}

/**
 * «Что сделать сейчас» на экране входов — следующий шаг словами: что обязательно, что на выбор и что сохраняет
 * «Сохранить». Только для веса (тест 1RM / 5×5 / 5×3); для резины объяснение — в «Зачем это нужно». Правила не
 * меняются: без массы тела и шага тест не начинается; нагрузку силы даёт тест или недавний 5×5 / 5×3 (V5.6 §8, §10).
 */
export function describeSetupSteps(missing: string[]): string[] {
  if (!missing.includes("one_rep_max")) {
    return [];
  }
  const steps: string[] = [];
  const required = [
    missing.includes("body_mass") ? "ваш вес" : null, missing.includes("load_step") ? "шаг дополнительного веса" : null,
  ].filter((item): item is string => item !== null);
  if (required.length > 0) {
    steps.push(`Обязательно впишите ${required.join(" и ")} — без этого не начать ни тест, ни тренировку.`);
  }
  steps.push(
    "Затем одно из двух: пройдите тест 1RM ниже — отдельным свежим днём, не после объёма; или впишите недавний "
    + "5×5 / 5×3 и нажмите «Сохранить».",
  );
  steps.push("«Сохранить» записывает числа из полей; результат теста сохраняется в самом тесте. После этого экран покажет первую тренировку.");
  return steps;
}

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

/** Итог записанного теста 1RM (POST …/course/one-rep-max, V5.6 §10, review #318). */
export interface OneRepMaxOutcomeV2 {
  e1rm_kg: string | null;
  conservative: boolean;
  sets_used?: number;
  outcome?: "completed" | "stopped";
  confirmed?: boolean;
  last_successful_single_kg?: string | null;
}

/**
 * Текст итога теста. Подтверждённым 1RM называется только оконченный стандартизированный тест (неудача или
 * восьмой подход) с успешным одиночным подходом. Добровольная остановка — сохранённый факт: последний
 * успешный одиночный вес показывается, но это не 1RM и нагрузку он не задаёт.
 */
export function describeOneRepMaxOutcome(result: OneRepMaxOutcomeV2 | null): string {
  if (result === null) {
    return "Результат не записан.";
  }
  const single = result.last_successful_single_kg ?? null;
  if (result.outcome === "stopped") {
    const best = single === null ? "успешного одиночного подхода не было" : `последний успешный одиночный: +${single} кг`;
    return `Тест остановлен вами и сохранён (${best}). Это не подтверждённый 1RM — вес силовых подходов по нему не назначается.`;
  }
  if (result.e1rm_kg === null) {
    return "Тест окончен и сохранён, но успешного одиночного подхода нет — 1RM не назначен.";
  }
  return `1RM: +${result.e1rm_kg} кг${result.conservative ? " (консервативно)" : ""}`;
}
