import { Button, Input, Section, Select } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  fetchTimezoneOptions,
  submitOnboardingBaseline,
  submitOnboardingQuestionnaire,
  type OnboardingStep,
  type TimezoneOption,
} from "./api";
import { parseOptionalWeight } from "./WorkoutScreen";

type Props = {
  initDataRaw: string;
  /** "done" никогда не приходит сюда — App.tsx рендерит этот экран только
   * пока онбординг не завершён (см. App.tsx). "not_registered" стартует с
   * того же самого первого вопроса, что и "baseline" (POST
   * /api/onboarding/baseline сам заводит User, если строки ещё нет) —
   * различать эти два случая тут незачем, оба начинают с замера. */
  startStep: OnboardingStep;
  onComplete: () => void;
};

type ScreenState =
  | { phase: "baseline_input" }
  | { phase: "baseline_confirm"; reps: number }
  | { phase: "baseline_motivation"; reps: number; message: string }
  | { phase: "questionnaire"; step: number };

/** Тот же текст, что app.bot.texts.BASELINE_GUIDE — независимая копия, как
 * и весь остальной пользовательский текст интерфейса Mini App (прямого
 * шаринга Python↔TS в проекте нет, см. WorkoutScreen.tsx). */
const BASELINE_GUIDE =
  "Замер простой: сделай максимум подтягиваний со своим весом, один подход. " +
  "Понадобится турник. Если ни одного повторения не получается — это тоже " +
  "результат, просто напиши 0.";
const WELCOME_AFTER_BASELINE = "Осталась короткая анкета — 5 коротких вопросов.";

const QUESTIONNAIRE_STEPS = ["weight", "height", "gender", "birth_date", "timezone"] as const;
type QuestionnaireStep = (typeof QUESTIONNAIRE_STEPS)[number];

const GENDER_OPTIONS: { value: "male" | "female"; label: string }[] = [
  { value: "male", label: "Мужской" },
  { value: "female", label: "Женский" },
];

/** Замер + анкета (issue #124, PR 2) — второй из трёх бот-only кусков,
 * перенесённых в Mini App (после разминки, PR 1). Пошаговость сохранена
 * (issue прямо просил не сводить анкету в одну форму): замер — отдельный
 * шаг с подтверждением (та же защита от опечатки, что
 * waiting_for_baseline_confirm бота, только на фронтенде — в БД ничего не
 * попадает, пока не нажато "Да", см. api.ts::submitOnboardingBaseline),
 * анкета — 5 экранов, один вопрос за раз, с кнопкой "Назад", один POST в
 * конце (не по шагам — см. обоснование в комментарии к issue: анкета
 * дешёвая форма без побочных эффектов до сабмита, в отличие от целой
 * тренировки, которая персистится по шагам, issue #61). */
export function OnboardingScreen({ initDataRaw, startStep, onComplete }: Props) {
  const [state, setState] = useState<ScreenState>(
    startStep === "questionnaire" ? { phase: "questionnaire", step: 0 } : { phase: "baseline_input" },
  );
  const [repsInput, setRepsInput] = useState("");
  const [weightKg, setWeightKg] = useState("");
  const [heightCm, setHeightCm] = useState("");
  const [gender, setGender] = useState<"male" | "female" | "">("");
  const [birthDate, setBirthDate] = useState("");
  const [timezone, setTimezone] = useState("");
  const [timezoneOptions, setTimezoneOptions] = useState<TimezoneOption[]>([]);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    // Автоопределение часового пояса браузера (согласовано в плане issue
    // #124 как осознанное расхождение с ботом — там вместо этого свободный
    // ввод города) — только предзаполняет значение по умолчанию, реальный
    // список для явного выбора — ниже, из fetchTimezoneOptions.
    try {
      const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (detected) {
        setTimezone(detected);
      }
    } catch {
      // Молча — просто нет значения по умолчанию, выбор всё равно доступен.
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetchTimezoneOptions(initDataRaw)
      .then((data) => {
        if (!cancelled) {
          setTimezoneOptions(data.options);
        }
      })
      .catch(() => {
        // Молча — список остаётся пустым/с одним автоопределённым значением.
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  function handleBaselineNext() {
    const trimmed = repsInput.trim();
    if (!/^\d+$/.test(trimmed) || Number(trimmed) > 999) {
      setFormError("Не разобрал число повторений — пришли просто цифру, например: 8");
      return;
    }
    setFormError(null);
    setState({ phase: "baseline_confirm", reps: Number(trimmed) });
  }

  async function handleBaselineConfirm(reps: number) {
    setSubmitting(true);
    setFormError(null);
    try {
      const result = await submitOnboardingBaseline(initDataRaw, reps);
      setState({ phase: "baseline_motivation", reps: result.reps, message: result.motivation_message });
    } catch (error) {
      setFormError(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  }

  function validateQuestionnaireStep(step: QuestionnaireStep): string | null {
    if (step === "weight") {
      const weight = parseOptionalWeight(weightKg);
      if (!weight.ok || weight.value === null) {
        return "Не разобрал число — пришли вес в кг, например: 78";
      }
    }
    if (step === "height") {
      const height = Number(heightCm.trim());
      if (!Number.isFinite(height) || height <= 0) {
        return "Не разобрал число — пришли рост в см, например: 180";
      }
    }
    if (step === "gender" && gender === "") {
      return "Выбери пол.";
    }
    if (step === "birth_date") {
      if (birthDate === "") {
        return "Укажи дату рождения.";
      }
      if (new Date(birthDate) > new Date()) {
        return "Эта дата ещё не наступила — пришли настоящую дату рождения.";
      }
    }
    if (step === "timezone" && timezone === "") {
      return "Выбери часовой пояс.";
    }
    return null;
  }

  async function handleQuestionnaireSubmit() {
    // Уже провалидировано в validateQuestionnaireStep на каждом шаге — к
    // моменту вызова этой функции (последний шаг пройден через
    // handleQuestionnaireNext) weight гарантированно ok со значением.
    const weight = parseOptionalWeight(weightKg);
    const weightKgValue = weight.ok ? weight.value : null;
    if (weightKgValue === null) {
      setFormError("Не разобрал число — пришли вес в кг, например: 78");
      return;
    }

    setSubmitting(true);
    setFormError(null);
    try {
      await submitOnboardingQuestionnaire(initDataRaw, {
        weight_kg: weightKgValue,
        height_cm: Math.round(Number(heightCm.trim())),
        gender: gender as "male" | "female",
        birth_date: birthDate,
        timezone,
      });
      onComplete();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : String(error));
      setSubmitting(false);
    }
  }

  function handleQuestionnaireNext(stepIndex: number) {
    const error = validateQuestionnaireStep(QUESTIONNAIRE_STEPS[stepIndex]);
    if (error) {
      setFormError(error);
      return;
    }
    setFormError(null);
    if (stepIndex === QUESTIONNAIRE_STEPS.length - 1) {
      void handleQuestionnaireSubmit();
      return;
    }
    setState({ phase: "questionnaire", step: stepIndex + 1 });
  }

  if (state.phase === "baseline_input") {
    return (
      <div>
        <p className="plan-title">Замер</p>
        <p className="screen-message">{BASELINE_GUIDE}</p>
        <Section className="block-section">
          <Input
            header="Сколько подтягиваний вышло?"
            type="number"
            inputMode="numeric"
            min={0}
            max={999}
            aria-label="Число подтягиваний"
            value={repsInput}
            onChange={(e) => setRepsInput(e.target.value)}
          />
        </Section>
        {formError && <p className="error-banner">{formError}</p>}
        <Button className="action-button" size="l" stretched onClick={handleBaselineNext}>
          Далее
        </Button>
      </div>
    );
  }

  if (state.phase === "baseline_confirm") {
    return (
      <div>
        <p className="plan-title">Всё верно?</p>
        <p className="screen-message">Записал: {state.reps} повторений. Всё верно?</p>
        {formError && <p className="error-banner">{formError}</p>}
        <Button
          className="action-button"
          size="l"
          stretched
          disabled={submitting}
          onClick={() => void handleBaselineConfirm(state.reps)}
        >
          Да
        </Button>
        <Button
          className="action-button"
          size="l"
          stretched
          mode="outline"
          disabled={submitting}
          onClick={() => setState({ phase: "baseline_input" })}
        >
          Ввести заново
        </Button>
      </div>
    );
  }

  if (state.phase === "baseline_motivation") {
    return (
      <div>
        <p className="plan-title">Уровень зафиксирован</p>
        <p className="screen-message">{state.message}</p>
        <p className="screen-message">{WELCOME_AFTER_BASELINE}</p>
        <Button
          className="action-button"
          size="l"
          stretched
          onClick={() => setState({ phase: "questionnaire", step: 0 })}
        >
          Продолжить
        </Button>
      </div>
    );
  }

  const { step } = state;
  const current = QUESTIONNAIRE_STEPS[step];
  const isLastStep = step === QUESTIONNAIRE_STEPS.length - 1;

  return (
    <div>
      <p className="plan-title">Анкета</p>
      <p className="hint">
        Шаг {step + 1} из {QUESTIONNAIRE_STEPS.length}
      </p>

      <Section className="block-section">
        {current === "weight" && (
          <Input
            header="Твой вес в кг?"
            type="number"
            inputMode="decimal"
            min={0}
            step="0.1"
            placeholder="Например: 78"
            aria-label="Вес, кг"
            value={weightKg}
            onChange={(e) => setWeightKg(e.target.value)}
          />
        )}
        {current === "height" && (
          <Input
            header="Рост в см?"
            type="number"
            inputMode="numeric"
            min={0}
            placeholder="Например: 180"
            aria-label="Рост, см"
            value={heightCm}
            onChange={(e) => setHeightCm(e.target.value)}
          />
        )}
        {current === "gender" && (
          <Select
            header="Пол?"
            aria-label="Пол"
            value={gender}
            onChange={(e) => setGender(e.target.value as "male" | "female" | "")}
          >
            <option value="">Выбери</option>
            {GENDER_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        )}
        {current === "birth_date" && (
          <Input
            header="Дата рождения?"
            type="date"
            aria-label="Дата рождения"
            value={birthDate}
            onChange={(e) => setBirthDate(e.target.value)}
          />
        )}
        {current === "timezone" && (
          <Select
            header="Часовой пояс?"
            aria-label="Часовой пояс"
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
          >
            <option value="">Выбери</option>
            {timezoneOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        )}
      </Section>

      {formError && <p className="error-banner">{formError}</p>}

      <Button
        className="action-button"
        size="l"
        stretched
        disabled={submitting}
        onClick={() => handleQuestionnaireNext(step)}
      >
        {isLastStep ? "Готово" : "Далее"}
      </Button>
      {step > 0 && (
        <Button
          className="action-button"
          size="l"
          stretched
          mode="outline"
          disabled={submitting}
          onClick={() => setState({ phase: "questionnaire", step: step - 1 })}
        >
          ← Назад
        </Button>
      )}
    </div>
  );
}
