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
import { BackdateForm } from "./BackdateForm";
import { ElectiveScreen } from "./ElectiveScreen";
import { FreeWorkoutScreen } from "./FreeWorkoutScreen";
import { LiveWorkoutScreen } from "./LiveWorkoutScreen";

type Props = {
  initDataRaw: string;
  /** Живая тренировка (issue #59) держит несохранённый ввод только во
   * фронтенд-состоянии до финальной отправки — переключение нижних вкладок
   * размонтировало бы этот экран и потеряло бы его молча (см. App.tsx),
   * поэтому WorkoutScreen сообщает наверх, когда такой режим активен. */
  onLiveActiveChange?: (active: boolean) => void;
  /** FAQ "Как выбрать резину" (issue #102) — открывает FaqScreen через
   * App.tsx, прокидывается дальше в BlockForm/LiveWorkoutScreen, где
   * фактически показана сноска у выбора резины на BAND. */
  onOpenFaq: () => void;
};

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
export const STATUS_MESSAGES: Record<string, string> = {
  no_access: "Нет активной подписки. Оформи её в боте, потом возвращайся сюда.",
  first_workout: "Это твоя первая тренировка — замер и выбор снаряда пока доступны только в боте.",
  too_early: "Ещё рано для следующей тренировки — минимальный отдых между тренировками не прошёл.",
  gap_retest_required: "Был долгий перерыв — нужен повторный замер, начни его в боте.",
  equipment_setup_required: "Нужно заново выбрать снаряд для одного из блоков — сделай это в боте.",
  no_active_set: "Не получилось открыть тренировочный цикл. Напиши в поддержку через бота.",
  not_onboarded: "Похоже, ты ещё не проходил онбординг — начни его в боте.",
};

// Ежемесячный тест на максимум блока на объём (issue #89, форма перенесена
// в Mini App — issue #105) — тот же текст, что app.bot.texts.
// VOLUME_DELOAD_PROMPT (независимая копия, как и весь остальной текст
// интерфейса, см. WORK_SETS_GROWTH_NOTICES выше), без числа-ориентира
// (поправка продукта того же issue — даже необязательный ориентир вводил
// в заблуждение резким скачком от рабочей цели).
const DELOAD_TEST_PROMPT =
  "Сегодня — тест на максимум по блоку на объём. Раз в 30 дней вместо обычной структуры блока — " +
  "один подход на максимум, без отягощения: подтянись столько раз, сколько реально сможешь, до отказа. " +
  "Никакого обязательного числа нет — просто честный максимум за один подход. На основной прогресс это " +
  "не влияет — только в статистику. Блок Б дальше пройдёт как в обычной тренировке.";
const DELOAD_DONE_NOTE =
  "😌 Это был ежемесячный тест на максимум блока на объём — цель и число рабочих подходов не менялись.";

// Тот же текст, что app.bot.texts.WORK_SETS_GROWTH_STALL_NOTICE/
// WORK_SETS_GROWTH_CEILING_NOTICE (issue #79) — независимая копия строки,
// как и весь остальной текст интерфейса (прямого шаринга Python↔TS в
// проекте нет), причина одна и та же (plan.work_sets_growth_reason).
const WORK_SETS_GROWTH_NOTICES: Record<string, string> = {
  stall: "Несколько тренировок подряд без роста — добавлен ещё один подход, чтобы продолжить расти через объём.",
  ceiling:
    "Отличный результат — вы уперлись в потолок повторений за подход, поэтому цель снижена, " +
    "а число подходов увеличено, чтобы продолжить расти дальше.",
};

function closeMiniApp() {
  (window as unknown as { Telegram?: { WebApp?: { close?: () => void } } }).Telegram?.WebApp?.close?.();
}

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

export function SetInputGrid({
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

export function BandItemSelect({
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
  isHeavy = false,
  onOpenFaq,
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
  /** Чётная ("тяжёлая") тренировка блока Б (issue #97) — фиксированные
   * повторения, повышенный вес (уже подставлен в equipmentLabel сервером,
   * см. app/web/routes.py::_resolve_plan_context), только заголовок/подпись
   * отличаются — раскладка полей ввода та же (4 рабочих + 1 на максимум). */
  isHeavy?: boolean;
  /** Сноска "Как выбрать резину" (issue #102) — короткая подсказка рядом с
   * выбором резины, полный текст только на FaqScreen (не дублируется тут).
   * Опционально: HistoryEditForm переиспользует BlockForm для правки уже
   * записанной тренировки и не имеет перехода на FaqScreen — там сноска
   * просто не показывается, не сломанная ссылка в никуда. */
  onOpenFaq?: () => void;
}) {
  return (
    <Section
      className="block-section"
      header={isHeavy ? `Блок ${letter} — тяжёлая тренировка 🏋️` : `Блок ${letter} — цель ${target}`}
    >
      <div className="block-header">
        <div className="block-badge">{letter}</div>
        <p className="block-subtitle">
          {isHeavy
            ? "Фиксированные 3 повторения в каждом подходе"
            : `${workSets} рабочих ${workSets === 1 ? "подход" : "подхода"}`}
          {" · "}
          {equipmentLabel ?? "снаряд не выбран"}
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

      {/* Сноска "Как выбрать резину" (issue #102) — короткая подсказка, не
          полный текст (полный текст только на FaqScreen, открывается этой
          же кнопкой). Показывается при любом BAND, не только когда уже есть
          личный список резин — актуально и до первого добавления резины. */}
      {equipmentType === "band" && onOpenFaq && (
        <p className="hint">
          Тугая резина — целевое число повторений даётся легко; слабая — не получается даже с ней.{" "}
          <button type="button" className="hint-link" onClick={onOpenFaq}>
            Как выбрать резину →
          </button>
        </p>
      )}
    </Section>
  );
}

/** Тест на максимум блока A (issue #89, форма в Mini App — issue #105) —
 * один вопрос вместо обычной сетки рабочих подходов + максимума, тот же
 * смысл, что "пришли результат одним числом" в боте (VOLUME_DELOAD_PROMPT).
 * Снаряд принудительно свой вес (сервер уже это гарантирует, см.
 * app/web/routes.py::_resolve_plan_context) — актуального веса/резины тут
 * нет и быть не может. */
function DeloadBlockAForm({ maxValue, onMaxChange }: { maxValue: string; onMaxChange: (value: string) => void }) {
  return (
    <Section className="block-section" header="Блок A — тест на максимум">
      <p className="block-subtitle">{DELOAD_TEST_PROMPT}</p>
      <span className="field-label">Результат (одно число)</span>
      <div className="set-grid">
        <input
          className="set-input max-input"
          type="number"
          inputMode="numeric"
          min={0}
          max={999}
          aria-label="Блок A, тест на максимум"
          value={maxValue}
          onChange={(e) => onMaxChange(e.target.value)}
        />
      </div>
    </Section>
  );
}

export function WorkoutScreen({ initDataRaw, onLiveActiveChange, onOpenFaq }: Props) {
  const [showBackdate, setShowBackdate] = useState(false);
  const [showLive, setShowLive] = useState(false);
  const [showElective, setShowElective] = useState(false);
  const [showFreeWorkout, setShowFreeWorkout] = useState(false);
  // Экран выбора действия по умолчанию (issue #108) — форма ввода
  // результата сегодняшней тренировки больше не показывается сразу под
  // planом, а только после явного нажатия 4-й кнопки "📝 Внести результат
  // тренировки", симметрично остальным трём режимам.
  const [showForm, setShowForm] = useState(false);
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
    // Тест на максимум (issue #105) — один подход без раскладки, тот же
    // смысл, что parse_reps("15") в боте: working_reps=[], max_reps=введённое
    // число. parseSetValues(blockAWorking) не подходит здесь — пустой массив
    // для неё невалиден (используется как "поля не заполнены" для обычного
    // блока A), а для теста это ожидаемое штатное значение.
    const workingA = plan.is_deload_a ? [] : parseSetValues(blockAWorking);
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

  if (showBackdate) {
    return (
      <BackdateForm
        initDataRaw={initDataRaw}
        onCancel={() => setShowBackdate(false)}
        onDone={() => setShowBackdate(false)}
      />
    );
  }

  if (showLive) {
    return (
      <LiveWorkoutScreen
        initDataRaw={initDataRaw}
        onActiveChange={onLiveActiveChange}
        onCancel={() => setShowLive(false)}
        onDone={() => setShowLive(false)}
        onOpenFaq={onOpenFaq}
      />
    );
  }

  if (showElective) {
    return (
      <ElectiveScreen
        initDataRaw={initDataRaw}
        onCancel={() => setShowElective(false)}
        onDone={() => setShowElective(false)}
      />
    );
  }

  if (showFreeWorkout) {
    return (
      <FreeWorkoutScreen
        initDataRaw={initDataRaw}
        onCancel={() => setShowFreeWorkout(false)}
        onDone={() => setShowFreeWorkout(false)}
      />
    );
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
        {/* Проактивное предложение факультатива на статусе "сегодня отдых"
            (issue #94) — тот же принцип, что TOO_EARLY_ELECTIVE_BUTTON у
            бота (app/bot/handlers/workout.py::resolve_rest_day_notice):
            факультатив не заменяет обычную тренировку и не гейтуется её
            статусом (см. app/web/routes.py::get_elective_plan), поэтому
            кнопка ведёт на тот же ElectiveScreen, что и в обычном режиме
            ниже, просто выделена здесь первой, раз статус уже too_early. */}
        {state.status === "too_early" && (
          <Button className="action-button" size="l" stretched onClick={() => setShowElective(true)}>
            🎯 Сделать факультатив
          </Button>
        )}
        <Button className="action-button" size="l" stretched onClick={closeMiniApp}>
          Открыть в боте
        </Button>
        <Button className="action-button" size="l" stretched mode="outline" onClick={() => setShowBackdate(true)}>
          🔁 Внести пропущенную тренировку
        </Button>
        {/* Свободные подтягивания (issue #109) не гейтуются готовностью к
            обычной тренировке, как и бэкдейт выше — доступны и на статусе
            "сегодня отдых", и на любом другом not_ready. */}
        <Button className="action-button" size="l" stretched mode="outline" onClick={() => setShowFreeWorkout(true)}>
          ➕ Внести свободные подтягивания
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
          {result.is_deload_a ? (
            <p className="hint">
              {DELOAD_DONE_NOTE} Цель блока Б на следующую тренировку — {result.target_b} (
              {result.equipment_b?.label}).
            </p>
          ) : (
            <p className="hint">
              Цели на следующую тренировку: блок A — {result.target_a} ({result.equipment_a?.label}), блок B —{" "}
              {result.target_b} ({result.equipment_b?.label}).
            </p>
          )}
        </div>
        <Button className="action-button" size="l" stretched onClick={closeMiniApp}>
          Готово
        </Button>
      </div>
    );
  }

  const { plan } = state;
  // Баннеры показываются сразу на экране выбора действия, а не только
  // вместе с формой (issue #108) — это контекст, важный до выбора действия
  // (снижена ли цель блока A из-за перерыва, вырос ли объём блока), а не
  // только при непосредственном вводе результата.
  const banners = (
    <>
      {plan.is_gap_rollback && (
        <p className="gap-banner">Был перерыв — цель блока A немного снижена, это нормально.</p>
      )}
      {plan.work_sets_growth_reason && (
        <p className="gap-banner">{WORK_SETS_GROWTH_NOTICES[plan.work_sets_growth_reason]}</p>
      )}
    </>
  );

  if (!showForm) {
    return (
      <div>
        <p className="plan-title">Текущий план</p>
        {banners}

        <div className="workout-mode-buttons">
          {/* Живая тренировка (таймер по подходам) не адаптирована под
              структуру теста на максимум (issue #105, тот же принцип сужения
              скоупа, что и у остальных статусов Этапа 1) — на день теста
              кнопка скрыта, обычный режим ниже её заменяет. */}
          {!plan.is_deload_a && (
            <Button mode="outline" size="s" onClick={() => setShowLive(true)}>
              ⏱ Тренировка в реальном времени
            </Button>
          )}
          <Button mode="outline" size="s" onClick={() => setShowBackdate(true)}>
            🔁 Внести пропущенную тренировку
          </Button>
          <Button mode="outline" size="s" onClick={() => setShowElective(true)}>
            🎯 Факультатив
          </Button>
          <Button mode="outline" size="s" onClick={() => setShowFreeWorkout(true)}>
            ➕ Внести свободные подтягивания
          </Button>
          <Button mode="outline" size="s" onClick={() => setShowForm(true)}>
            📝 Внести результат тренировки
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div>
      <p className="plan-title">Текущий план</p>
      {banners}

      <Button mode="plain" size="s" onClick={() => setShowForm(false)}>
        ← Назад к выбору действия
      </Button>

      {plan.is_deload_a ? (
        <DeloadBlockAForm maxValue={blockAMax} onMaxChange={setBlockAMax} />
      ) : (
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
          onOpenFaq={onOpenFaq}
        />
      )}

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
        isHeavy={plan.is_heavy_b}
        onOpenFaq={onOpenFaq}
      />

      <Textarea header="Комментарий (необязательно)" value={comment} onChange={(e) => setComment(e.target.value)} />

      {formError && <p className="error-banner">{formError}</p>}
      <Button className="action-button" size="l" stretched disabled={submitting} onClick={() => void handleSubmit(plan, false)}>
        Записать тренировку
      </Button>
    </div>
  );
}
