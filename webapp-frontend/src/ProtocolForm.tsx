import { Button, Input, Section, SegmentedControl } from "@telegram-apps/telegram-ui";
import { useState } from "react";

import { TimeInputField } from "./TimeInputField";
import { formatSecondsAsMinutesSeconds } from "./timeInput";

export type ProtocolFormValue = Record<string, unknown>;

type ProtocolKind = "reps_sets" | "time_sets" | "max_effort" | "interval";

const KIND_LABELS: Record<ProtocolKind, string> = {
  reps_sets: "Повторения",
  time_sets: "Время",
  max_effort: "Максимум",
  interval: "Интервалы",
};

function kindFromProtocol(protocol: ProtocolFormValue | null): ProtocolKind {
  const type = protocol?.type;
  if (type === "reps_sets" || type === "time_sets" || type === "max_effort" || type === "interval") {
    return type;
  }
  return "reps_sets";
}

/** Phase C4b-1 (issue #188) — количество рабочих интервалов, та же
 * формула, что app/domain/interval_timing.py::calculate_completed_cycles
 * (не приближённо, "≈" не используется — issue #188 раздел 7 прямо
 * запрещает). elapsed для превью — весь total_duration_seconds (сколько
 * рабочих фаз ПОМЕСТИТСЯ в заданное общее время), не текущее "прошедшее
 * время" (превью считается до старта тренировки, elapsed здесь
 * концептуально другое значение, чем во время live-исполнения, но
 * формула идентична — то же самое "сколько WORK-фаз завершится за total
 * секунд"). */
function calculateWorkIntervalsPreview(totalSeconds: number, workSeconds: number, restSeconds: number): number {
  if (workSeconds <= 0) {
    return 0;
  }
  const cappedElapsed = Math.min(totalSeconds, totalSeconds);
  if (cappedElapsed < workSeconds) {
    return 0;
  }
  const cycleDuration = workSeconds + restSeconds;
  if (cycleDuration <= 0) {
    return 0;
  }
  return Math.floor((cappedElapsed - workSeconds) / cycleDuration) + 1;
}

type Props = {
  initialExerciseName: string;
  initialProtocol: ProtocolFormValue | null;
  onCancel: () => void;
  onSubmit: (protocol: ProtocolFormValue) => void;
  submitLabel: string;
};

/**
 * Phase C4b-1 (issue #188) — выбор типа тренировки + форма параметров,
 * один компонент на все 4 типа (переключение по SegmentedControl, не 4
 * отдельных экрана). Собирает protocol dict, соответствующий
 * app.domain.workout_protocol.UserWorkoutProtocol — backend валидирует
 * повторно, здесь только UI-уровень (issue #188, раздел 13 — "не
 * показывать raw backend JSON", человекочитаемые ошибки до отправки).
 *
 * MAX-форма (Phase C4b-1.5, issue #188) включает поле "Отдых" —
 * StaticMaxEffort.rest_seconds добавлен в app/domain/workout_protocol.py
 * специально под этот UX-контракт (изначальная Phase A1 схема его не
 * несла, C4b-1 честно зафиксировал это как расхождение вместо обманчивого
 * no-op поля; C4b-1.5 закрывает разрыв на backend+frontend вместе).
 */
export function ProtocolForm({ initialExerciseName, initialProtocol, onCancel, onSubmit, submitLabel }: Props) {
  const [kind, setKind] = useState<ProtocolKind>(kindFromProtocol(initialProtocol));

  const initialPrescription = (initialProtocol?.prescription ?? {}) as Record<string, unknown>;
  const [sets, setSets] = useState<number>(Number(initialPrescription.sets ?? 3));
  const [reps, setReps] = useState<number>(Number(initialPrescription.reps ?? 10));
  const [durationSeconds, setDurationSeconds] = useState<number>(Number(initialPrescription.duration_seconds ?? 30));
  const [restSeconds, setRestSeconds] = useState<number>(Number(initialProtocol?.rest_seconds ?? 60));
  const [attempts, setAttempts] = useState<number>(Number(initialPrescription.attempts ?? 1));
  const [maxRestSeconds, setMaxRestSeconds] = useState<number>(Number(initialProtocol?.rest_seconds ?? 0));
  const [totalSeconds, setTotalSeconds] = useState<number>(Number(initialProtocol?.total_duration_seconds ?? 180));
  const [workSeconds, setWorkSeconds] = useState<number>(Number(initialProtocol?.work_seconds ?? 10));
  const [intervalRestSeconds, setIntervalRestSeconds] = useState<number>(Number(initialProtocol?.rest_seconds ?? 20));
  const [startsWith, setStartsWith] = useState<"work" | "rest">(
    initialProtocol?.starts_with === "rest" ? "rest" : "work",
  );

  const [validationError, setValidationError] = useState<string | null>(null);

  function buildProtocol(): ProtocolFormValue | null {
    if (kind === "reps_sets") {
      if (sets <= 0) return fail("Укажите количество подходов");
      if (reps <= 0) return fail("Укажите цель по повторениям");
      if (restSeconds < 0) return fail("Отдых не может быть отрицательным");
      return { type: "reps_sets", prescription: { source: "static", sets, reps }, rest_seconds: restSeconds };
    }
    if (kind === "time_sets") {
      if (sets <= 0) return fail("Укажите количество подходов");
      if (durationSeconds <= 0) return fail("Укажите длительность подхода");
      if (restSeconds < 0) return fail("Отдых не может быть отрицательным");
      return {
        type: "time_sets",
        prescription: { source: "static", sets, duration_seconds: durationSeconds },
        rest_seconds: restSeconds,
      };
    }
    if (kind === "max_effort") {
      if (attempts <= 0) return fail("Укажите количество попыток");
      if (maxRestSeconds < 0) return fail("Отдых не может быть отрицательным");
      return {
        type: "max_effort",
        prescription: { source: "static", attempts },
        rest_seconds: maxRestSeconds,
      };
    }
    // interval
    if (totalSeconds <= 0) return fail("Укажите общую длительность тренировки");
    if (workSeconds <= 0) return fail("Укажите длительность фазы работы");
    if (intervalRestSeconds < 0) return fail("Отдых не может быть отрицательным");
    if (workSeconds > totalSeconds) return fail("Работа не может быть длиннее всей тренировки");
    return {
      type: "interval", total_duration_seconds: totalSeconds, work_seconds: workSeconds,
      rest_seconds: intervalRestSeconds, starts_with: startsWith,
    };
  }

  function fail(message: string): null {
    setValidationError(message);
    return null;
  }

  function handleSubmit() {
    setValidationError(null);
    const protocol = buildProtocol();
    if (protocol !== null) {
      onSubmit(protocol);
    }
  }

  return (
    <div>
      <p className="plan-title">{initialExerciseName}</p>
      <p className="block-subtitle">Тип тренировки</p>
      <SegmentedControl>
        {(Object.keys(KIND_LABELS) as ProtocolKind[]).map((option) => (
          <SegmentedControl.Item key={option} selected={kind === option} onClick={() => setKind(option)}>
            {KIND_LABELS[option]}
          </SegmentedControl.Item>
        ))}
      </SegmentedControl>

      {kind === "reps_sets" && (
        <Section className="block-section">
          <NumberField header="Подходы" value={sets} onChange={setSets} />
          <NumberField header="Повторения" value={reps} onChange={setReps} />
          <TimeInputField header="Отдых" seconds={restSeconds} onChange={setRestSeconds} />
        </Section>
      )}

      {kind === "time_sets" && (
        <Section className="block-section">
          <NumberField header="Подходы" value={sets} onChange={setSets} />
          <TimeInputField header="Длительность подхода" seconds={durationSeconds} onChange={setDurationSeconds} />
          <TimeInputField header="Отдых" seconds={restSeconds} onChange={setRestSeconds} />
        </Section>
      )}

      {kind === "max_effort" && (
        <Section className="block-section">
          <NumberField header="Попытки" value={attempts} onChange={setAttempts} />
          <TimeInputField header="Отдых" seconds={maxRestSeconds} onChange={setMaxRestSeconds} />
        </Section>
      )}

      {kind === "interval" && (
        <Section className="block-section">
          <TimeInputField header="Общее время" seconds={totalSeconds} onChange={setTotalSeconds} />
          <TimeInputField header="Работа" seconds={workSeconds} onChange={setWorkSeconds} />
          <TimeInputField header="Отдых" seconds={intervalRestSeconds} onChange={setIntervalRestSeconds} />
          <SegmentedControl>
            <SegmentedControl.Item selected={startsWith === "work"} onClick={() => setStartsWith("work")}>
              Работа
            </SegmentedControl.Item>
            <SegmentedControl.Item selected={startsWith === "rest"} onClick={() => setStartsWith("rest")}>
              Отдых
            </SegmentedControl.Item>
          </SegmentedControl>
          {workSeconds > 0 && totalSeconds >= workSeconds && (
            <p className="block-subtitle">
              {calculateWorkIntervalsPreview(totalSeconds, workSeconds, intervalRestSeconds)} рабочих интервалов
            </p>
          )}
        </Section>
      )}

      {validationError && <p className="gap-banner">{validationError}</p>}

      <Button className="action-button" size="l" stretched onClick={handleSubmit}>
        {submitLabel}
      </Button>
      <Button className="action-button" size="l" stretched mode="outline" onClick={onCancel}>
        Отмена
      </Button>
    </div>
  );
}

/** Phase C4b-1 (issue #188) — краткое summary для карточки в списке items,
 * тот же формат, что задание приводит примером: "Интервалы · 03:00 ·
 * 00:10 / 00:20" / "3 × 00:45 · отдых 01:00". */
export function formatProtocolSummary(protocol: ProtocolFormValue): string {
  const type = protocol.type;
  if (type === "interval") {
    const total = formatSecondsAsMinutesSeconds(Number(protocol.total_duration_seconds ?? 0));
    const work = formatSecondsAsMinutesSeconds(Number(protocol.work_seconds ?? 0));
    const rest = formatSecondsAsMinutesSeconds(Number(protocol.rest_seconds ?? 0));
    return `Интервалы · ${total} · ${work} / ${rest}`;
  }
  const prescription = (protocol.prescription ?? {}) as Record<string, unknown>;
  if (type === "reps_sets") {
    const rest = formatSecondsAsMinutesSeconds(Number(protocol.rest_seconds ?? 0));
    return `${prescription.sets ?? "?"} × ${prescription.reps ?? "?"} · отдых ${rest}`;
  }
  if (type === "time_sets") {
    const duration = formatSecondsAsMinutesSeconds(Number(prescription.duration_seconds ?? 0));
    const rest = formatSecondsAsMinutesSeconds(Number(protocol.rest_seconds ?? 0));
    return `${prescription.sets ?? "?"} × ${duration} · отдых ${rest}`;
  }
  if (type === "max_effort") {
    const rest = formatSecondsAsMinutesSeconds(Number(protocol.rest_seconds ?? 0));
    const attemptsCount = Number(prescription.attempts ?? 0);
    const attemptsWord = attemptsCount === 1 ? "попытка" : "попытки";
    return `${attemptsCount} ${attemptsWord} · отдых ${rest}`;
  }
  return "Тренировка";
}

function NumberField({ header, value, onChange }: { header: string; value: number; onChange: (value: number) => void }) {
  const [text, setText] = useState(String(value));
  return (
    <Input
      header={header}
      type="number"
      value={text}
      onChange={(event) => {
        setText(event.target.value);
        const parsed = Number(event.target.value);
        if (!Number.isNaN(parsed)) {
          onChange(parsed);
        }
      }}
    />
  );
}
