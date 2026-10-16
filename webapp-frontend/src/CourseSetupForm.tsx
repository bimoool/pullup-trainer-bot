/**
 * issue #305 (V5.6): ввод недостающих входов программы «Подтягивания» перед основной тренировкой
 * (PUT …/program-inclusions/{id}/course/inputs через apiV2.putCourseInputs). Показываются только поля из списка недостающих;
 * пустое не отправляется — сервер ничего не угадывает. Тест 1RM ведётся по шагам лестницы V5.6 §10
 * (OneRepMaxTest: подход за подходом с сервера, стоп после первой неудачи, ≤ 8 подходов, 48 ч от MAIN и
 * прошлого теста; можно явно остановиться самому — тогда это не подтверждённый 1RM); E1RM вручную не вводится. Недавний 5×5 / 5×3 со слов пользователя — альтернатива тесту (§9; сервер его не сверяет).
 * Пауза прибавок §9 — не вход: RecoveryCheckNotice показывается рядом со стартом и его не блокирует.
 */
import { Button, List, Section } from "@telegram-apps/telegram-ui";
import { useState } from "react";

import { LabeledInput } from "./LabeledField";
import { postOneRepMax, postOneRepMaxNextSet, putCourseInputs, type OneRmAttemptV2, type OneRmNextSetV2 } from "./apiV2";
import {
  assistanceConfirmations, type BandFields, COURSE_INPUT_FIELDS, courseInputsPayload, courseSetupLayout, describeCourseError,
  describeOneRepMaxOutcome, describePendingInputs, describeSetupNeeds, describeSetupSteps, loadStepWarning,
  ONE_RM_REQUIRED_INPUTS,
} from "./courseV5";

export interface AssistancePending {
  block: string;
  intent: string;
  proposed: { name?: string | null } | null;
}

const BLOCK_TITLE: Record<string, string> = {
  volume_a: "Объём A", volume_b: "Объём B", strength_a: "Сила A", strength_b: "Сила B",
};

const EMPTY_BAND: BandFields = { bodyweight: false, name: "", colour: "", attachment: "", body_position: "" };

function BandSection(
  { title, value, onChange, allowBodyweight, testId }:
  { title: string; value: BandFields; onChange: (next: BandFields) => void; allowBodyweight: boolean; testId: string },
) {
  return (
    <Section header={title} data-testid={testId}>
      {allowBodyweight && (
        <label className="live-hint">
          <input
            type="checkbox" checked={value.bodyweight} data-testid={`${testId}-bodyweight`}
            onChange={(e) => onChange({ ...value, bodyweight: e.target.checked })}
          />{" "}Без помощи (собственный вес)
        </label>
      )}
      {!value.bodyweight && (
        <>
          <LabeledInput
            label="Резина (модель/название)" data-testid={`${testId}-name`} value={value.name}
            onChange={(e) => onChange({ ...value, name: e.target.value })}
          />
          <LabeledInput
            label="Цвет резины" data-testid={`${testId}-colour`} value={value.colour}
            onChange={(e) => onChange({ ...value, colour: e.target.value })}
          />
          <LabeledInput
            label="Крепление" data-testid={`${testId}-attachment`} value={value.attachment}
            onChange={(e) => onChange({ ...value, attachment: e.target.value })}
          />
          <LabeledInput
            label="Положение: стопа или колено" data-testid={`${testId}-position`} value={value.body_position}
            onChange={(e) => onChange({ ...value, body_position: e.target.value })}
          />
        </>
      )}
    </Section>
  );
}

const SPEEDS: { value: "fast" | "normal" | "slow"; label: string }[] = [
  { value: "fast", label: "Быстро" }, { value: "normal", label: "Обычно" }, { value: "slow", label: "Медленно" },
];

/**
 * Тест 1RM в приложении (V5.6 §10) по существующему API: сервер выдаёт следующий подход лестницы
 * (BW×5 → +10% ×3 → +20% ×1 → одиночные по скорости), стоп — после первой неудачной/недействительной
 * попытки или восьмого подхода; результат — последний успешный одиночный доп. вес (2RM не используется).
 * Дойти до неудачи не обязательно: «Остановить тест» записывает явную добровольную остановку (без ложной
 * неудачи) — попытки сохраняются, но это не подтверждённый 1RM и нагрузку он не задаёт. Отдых между
 * подходами — 3 мин. Начало теста раньше 48 ч после тяжёлой тяговой работы или прошлого теста сервер
 * отклоняет сразу.
 */
export function OneRepMaxTest(
  { initDataRaw, inclusionId, onSaved, missing = [], typed = {} }:
  {
    initDataRaw: string; inclusionId: number; onSaved: () => void;
    /** Недостающие входы по серверу и введённое в форме, но ещё не сохранённое (масса тела, шаг веса). */
    missing?: string[]; typed?: Record<string, string>;
  },
) {
  const [attempts, setAttempts] = useState<OneRmAttemptV2[]>([]);
  const [next, setNext] = useState<OneRmNextSetV2 | null>(null);
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  async function step(done: OneRmAttemptV2[]) {
    setBusy(true);
    setError(null);
    try {
      const response = await postOneRepMaxNextSet(initDataRaw, inclusionId, done);
      setAttempts(done);
      setNext(response);
      setRunning(true);
    } catch (e) {
      setError(describeCourseError(e, "начать тест"));
    } finally {
      setBusy(false);
    }
  }

  /**
   * «Начать тест» раньше не отправлял форму: сервер проверял СОХРАНЁННЫЕ входы и отвечал 409 course_setup_required,
   * хотя шаг веса был введён. Теперь введённые масса тела и шаг веса сначала сохраняются (тем же PUT, что «Сохранить»),
   * а чего нет ни на сервере, ни в форме — называется словами, и фокус ставится на это поле. Правило не меняется:
   * без массы тела и шага лестница не начинается.
   */
  async function start() {
    const required = ONE_RM_REQUIRED_INPUTS.filter(({ item }) => missing.includes(item));
    const absent = required.filter(({ key }) => (typed[key] ?? "").trim() === "");
    if (absent.length > 0) {
      setError(`Чтобы начать тест, не хватает: ${describePendingInputs(absent.map(({ item }) => item))}. Заполните поле выше.`);
      (document.querySelector(`[data-testid="course-input-${absent[0].key}"]`) as HTMLElement | null)?.focus();
      return;
    }
    if (required.length > 0) {
      setBusy(true);
      setError(null);
      try {
        await putCourseInputs(
          initDataRaw, inclusionId, courseInputsPayload(Object.fromEntries(required.map(({ key }) => [key, typed[key]])), {}, false),
        );
      } catch (e) {
        setError(describeCourseError(e, "начать тест"));
        setBusy(false);
        return;
      }
    }
    await step([]);
  }

  async function record(stopped = false) {
    setBusy(true);
    setError(null);
    try {
      const saved = await postOneRepMax(initDataRaw, inclusionId, attempts, stopped);
      setResult(describeOneRepMaxOutcome(saved.one_rep_max));
      onSaved();
    } catch (e) {
      setError(describeCourseError(e, "сохранить тест"));
    } finally {
      setBusy(false);
    }
  }

  const current = next?.next_set ?? null;
  const attempt = (success: boolean, speed: "fast" | "normal" | "slow" | null = null) => {
    if (current === null) {
      return;
    }
    void step([...attempts, { load_kg: current.load_kg, reps: current.reps, success, speed }]);
  };

  return (
    <Section header="Вариант 1: тест 1RM в приложении" data-testid="one-rm-test">
      {!running && (
        <>
          <p className="live-hint">
            Отдельный свежий день: не после объёма и не раньше 48 ч после тяжёлой тяговой работы или прошлого
            теста 1RM. До 8 подходов, отдых 3 мин, стоп после первой неудачной попытки. Остановиться можно и
            раньше — тогда результат сохранится, но не будет подтверждённым 1RM.
          </p>
          <Button size="m" stretched mode="bezeled" disabled={busy} data-testid="one-rm-start" onClick={() => void start()}>
            Начать тест
          </Button>
        </>
      )}
      {running && current !== null && result === null && (
        <div data-testid="one-rm-step">
          <p className="live-plan" data-testid="one-rm-next">
            Подход {current.set_number} из 8: {Number(current.load_kg) > 0 ? `+${current.load_kg} кг` : "собственный вес"} × {current.reps}
          </p>
          {attempts.length > 0 && <p className="live-hint">Перед подходом — отдых {Math.round((next?.rest_seconds ?? 180) / 60)} мин.</p>}
          {current.reps === 1 ? (
            <div className="live-chips" data-testid="one-rm-speed">
              {SPEEDS.map((speed) => (
                <button key={speed.value} type="button" className="live-chip" disabled={busy} onClick={() => attempt(true, speed.value)}>
                  Получилось · {speed.label}
                </button>
              ))}
            </div>
          ) : (
            <Button size="m" stretched disabled={busy} data-testid="one-rm-success" onClick={() => attempt(true)}>
              Получилось чисто
            </Button>
          )}
          <Button size="m" stretched mode="outline" disabled={busy} data-testid="one-rm-fail" onClick={() => attempt(false)}>
            Не получилось / техника нарушена
          </Button>
          {attempts.length > 0 && (
            <Button size="m" stretched mode="plain" disabled={busy} data-testid="one-rm-stop" onClick={() => void record(true)}>
              Остановить тест (не подтверждённый 1RM)
            </Button>
          )}
        </div>
      )}
      {running && current === null && result === null && (
        <div data-testid="one-rm-finished">
          <p className="live-plan">Тест окончен: {attempts.length} подх.</p>
          <Button size="m" stretched disabled={busy} data-testid="one-rm-save" onClick={() => void record()}>
            Сохранить результат
          </Button>
        </div>
      )}
      {result !== null && <p className="live-plan" data-testid="one-rm-result">{result}</p>}
      {error !== null && <p className="live-hint" role="alert" data-testid="one-rm-error">{error}</p>}
    </Section>
  );
}

export function CourseSetupForm(
  { initDataRaw, inclusionId, missing, assistancePending = [], onSaved }:
  {
    initDataRaw: string; inclusionId: number; missing: string[]; assistancePending?: AssistancePending[];
    onSaved: () => void;
  },
) {
  const [numbers, setNumbers] = useState<Record<string, string>>({});
  const [volumeBand, setVolumeBand] = useState<BandFields>(EMPTY_BAND);
  const [strengthBand, setStrengthBand] = useState<BandFields>(EMPTY_BAND);
  // Смена помощи ждёт подтверждения ПОЛНОЙ записи резины; предложение по личному порядку — только название.
  const [pendingBands, setPendingBands] = useState<Record<string, BandFields>>(() => Object.fromEntries(
    assistancePending.map((entry) => [entry.block, { ...EMPTY_BAND, name: entry.proposed?.name ?? "" }]),
  ));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Данные (вес, шаг…) — сразу перед тестом 1RM, которому они нужны; недавний 5×5 / 5×3 — вариант 2 после теста.
  const layout = courseSetupLayout(missing);
  const allFields = Object.values(COURSE_INPUT_FIELDS).flat();
  const byKey = (keys: string[]) => keys.flatMap((key) => allFields.filter((field) => field.key === key));
  const fields = byKey(layout.dataKeys);
  const alternativeFields = byKey(layout.alternativeKeys);
  const needs = describeSetupNeeds(missing, assistancePending);
  const steps = describeSetupSteps(missing);

  const renderField = (field: { key: string; label: string; unit?: string; hint?: string }) => {
    const warning = field.key === "load_step_kg" ? loadStepWarning(numbers[field.key] ?? "") : null;
    return (
      <div key={field.key}>
        <LabeledInput
          label={field.unit ? `${field.label}, ${field.unit}` : field.label} hint={field.hint} inputMode="decimal"
          data-testid={`course-input-${field.key}`} value={numbers[field.key] ?? ""}
          onChange={(e) => setNumbers({ ...numbers, [field.key]: e.target.value })}
        />
        {warning !== null && (
          <p className="live-hint labeled-field-note" role="status" data-testid="course-load-step-warning">{warning}</p>
        )}
      </div>
    );
  };

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const body = courseInputsPayload(
        numbers,
        {
          volume: missing.includes("volume_assistance") ? volumeBand : undefined,
          strength: missing.includes("strength_assistance") ? strengthBand : undefined,
        },
        false,
      );
      const confirmations = assistanceConfirmations(
        assistancePending.map((entry) => ({ block: entry.block, fields: pendingBands[entry.block] ?? EMPTY_BAND })),
      );
      if (confirmations.length < assistancePending.length) {
        setError("Заполните резину целиком: модель, цвет, крепление и положение стопы/колена (или «без помощи»).");
      }
      if (confirmations.length > 0) {
        body.assistance_confirmations = confirmations;
      }
      const result = await putCourseInputs(initDataRaw, inclusionId, body);
      if (result.pending_inputs.length > 0) {
        setError(`Ещё не хватает: ${describePendingInputs(result.pending_inputs)}.`);
      }
      onSaved();
    } catch (e) {
      setError(describeCourseError(e, "сохранить"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <List data-testid="course-setup-form">
      {needs.length > 0 && (
        <Section header="Зачем это нужно" data-testid="course-setup-why">
          {needs.map((line) => <p key={line} className="live-hint labeled-field-note">{line}</p>)}
        </Section>
      )}
      {steps.length > 0 && (
        <Section header="Что сделать сейчас" data-testid="course-setup-steps">
          {steps.map((line) => <p key={line} className="live-hint labeled-field-note">{line}</p>)}
        </Section>
      )}
      {fields.length > 0 && (
        <Section header="Данные для расчёта программы" data-testid="course-setup-data">
          {fields.map(renderField)}
        </Section>
      )}
      {missing.includes("one_rep_max") && (
        <OneRepMaxTest initDataRaw={initDataRaw} inclusionId={inclusionId} onSaved={onSaved} missing={missing} typed={numbers} />
      )}
      {alternativeFields.length > 0 && (
        <Section header="Вариант 2: недавний 5×5 / 5×3 вместо теста" data-testid="course-setup-known-strength">
          <p className="live-hint labeled-field-note">
            Если вы недавно закрыли 5×5 или 5×3 с дополнительным весом — впишите его (хватит одного из двух) и
            нажмите «Сохранить». Тогда тест 1RM не нужен.
          </p>
          {alternativeFields.map(renderField)}
        </Section>
      )}
      {missing.includes("volume_assistance") && (
        <BandSection title="Объёмная резина" value={volumeBand} onChange={setVolumeBand} allowBodyweight={false} testId="course-volume-band" />
      )}
      {missing.includes("strength_assistance") && (
        <BandSection title="Помощь в силовом блоке" value={strengthBand} onChange={setStrengthBand} allowBodyweight testId="course-strength-band" />
      )}
      {assistancePending.map((entry) => (
        <BandSection
          key={entry.block}
          title={`${BLOCK_TITLE[entry.block] ?? entry.block}: ${entry.intent === "decrease_assistance" ? "меньше помощи" : "больше помощи"}${
            entry.proposed?.name ? ` — по вашему порядку: «${entry.proposed.name}»` : " — выберите резину"}`}
          value={pendingBands[entry.block] ?? EMPTY_BAND}
          onChange={(next) => setPendingBands({ ...pendingBands, [entry.block]: next })}
          allowBodyweight={entry.block.startsWith("strength")} testId={`course-confirm-${entry.block}`}
        />
      ))}
      {error !== null && <p className="live-hint" role="alert" data-testid="course-setup-error">{error}</p>}
      <div className="pre-transport">
        <Button className="action-button vs-primary" size="l" stretched disabled={saving} onClick={() => void save()} data-testid="course-setup-save">
          Сохранить
        </Button>
      </div>
    </List>
  );
}

/**
 * V5.6 §9: два занятия подряд хуже по обоим блокам — новые прибавки на паузе до проверки восстановления и
 * внешней тяговой нагрузки. Тренироваться можно (нагрузка удерживается); подтверждение снимает паузу.
 */
export function RecoveryCheckNotice(
  { initDataRaw, inclusionId, onSaved }: { initDataRaw: string; inclusionId: number; onSaved: () => void },
) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await putCourseInputs(initDataRaw, inclusionId, courseInputsPayload({}, {}, true));
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section header="Два занятия подряд хуже по обоим блокам" data-testid="course-recovery-check">
      <p className="live-hint">
        Новые прибавки на паузе, пока вы не проверите восстановление и внешнюю тяговую нагрузку. Тренироваться
        можно — нагрузка останется прежней.
      </p>
      <Button size="m" stretched mode="bezeled" disabled={busy} data-testid="course-recovery-confirm" onClick={() => void confirm()}>
        Восстановление и внешняя нагрузка проверены
      </Button>
      {error !== null && <p className="live-hint" role="alert">{error}</p>}
    </Section>
  );
}
