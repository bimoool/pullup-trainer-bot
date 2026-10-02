import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useRef, useState } from "react";

import { createSession, getWorkout, listWorkouts, type WorkoutResponseV2 } from "./apiV2";
import { EFFORT_SCALE, WORKOUT_COMMENT_MAX, WORKOUT_EFFORT_PROMPT } from "./effortScale";
import {
  ACTIVITY_TYPE_OPTIONS, buildActivityPayload, buildBackdatedPayload, dateError, durationError,
  metricForProtocol, setCountForProtocol, type SessionCreatePayload,
} from "./journalLog";
import { useBackButton } from "./useBackButton";
import { useProfileToday } from "./useProfileToday";

export type LogKind = "workout" | "activity";

/** Шторка «+ Записать» (Журнал и Главная): два пути записи прошедшей активности. */
export function LogActivitySheet({
  onPick, onClose,
}: {
  onPick: (kind: LogKind) => void;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useBackButton(() => closeRef.current(), []);

  // #290: как у остальных шторок — фокус внутрь, Escape закрывает, Tab не уходит под шторку,
  // при закрытии фокус возвращается на кнопку, открывшую шторку.
  useEffect(() => {
    const dialog = dialogRef.current;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab" || dialog === null) {
        return;
      }
      const items = Array.from(dialog.querySelectorAll<HTMLElement>("button:not(:disabled)"));
      if (items.length === 0) {
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (!dialog.contains(active) || (event.shiftKey && (active === first || active === dialog))) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (opener !== null && opener.isConnected) {
        opener.focus();
      }
    };
  }, []);

  return (
    <div className="home-sheet-backdrop" data-testid="journal-log-sheet-backdrop" onClick={onClose}>
      <div
        ref={dialogRef} className="home-sheet" role="dialog" aria-modal="true" aria-label="Записать" tabIndex={-1}
        data-testid="journal-log-sheet" onClick={(event) => event.stopPropagation()}
      >
        <button type="button" className="home-sheet-action" data-testid="log-option-workout" onClick={() => onPick("workout")}>
          Тренировку из моих
        </button>
        <button type="button" className="home-sheet-action" data-testid="log-option-activity" onClick={() => onPick("activity")}>
          Другую активность
        </button>
        <button type="button" className="home-sheet-action home-sheet-cancel" onClick={onClose}>
          Отмена
        </button>
      </div>
    </div>
  );
}

function EffortPicker({ value, onChange }: { value: string | null; onChange: (value: string | null) => void }) {
  return (
    <div className="log-field">
      <p className="log-label">{WORKOUT_EFFORT_PROMPT}</p>
      <div className="log-effort" role="group" aria-label="Усилие тренировки">
        {EFFORT_SCALE.map((option) => (
          <button
            key={option.value} type="button" data-testid={`log-effort-${option.value}`}
            className={value === option.value ? "search-chip search-chip-active" : "search-chip"}
            aria-pressed={value === option.value}
            onClick={() => onChange(value === option.value ? null : option.value)}
          >
            {option.value} {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function DateField({ value, today, onChange }: { value: string; today: string; onChange: (value: string) => void }) {
  return (
    <div className="log-field">
      <label className="log-label" htmlFor="log-date">Дата</label>
      <input
        id="log-date" className="log-input" type="date" max={today} value={value}
        data-testid="log-date" onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

function NoteField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <div className="log-field">
      <label className="log-label" htmlFor="log-note">Заметка</label>
      <textarea
        id="log-note" className="log-input" rows={3} maxLength={WORKOUT_COMMENT_MAX} value={value}
        data-testid="log-note" onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

/** Общий каркас формы записи: назад, ошибка, «Сохранить». */
function LogFormShell({
  title, error, saving, onBack, onSave, children,
}: {
  title: string;
  error: string | null;
  saving: boolean;
  onBack: () => void;
  onSave: () => void;
  children: React.ReactNode;
}) {
  useBackButton(onBack, [onBack]);
  return (
    <div className="log-form" data-testid="journal-log-form">
      <Button className="action-button" size="m" mode="outline" onClick={onBack}>← Назад</Button>
      <p className="plan-title">{title}</p>
      {children}
      {error !== null && <p className="gap-banner" data-testid="log-error">{error}</p>}
      <Button className="action-button" size="l" stretched loading={saving} onClick={onSave} data-testid="log-save">
        Сохранить
      </Button>
    </div>
  );
}

async function submit(
  initDataRaw: string, date: string, payload: SessionCreatePayload, setError: (message: string | null) => void,
  setSaving: (saving: boolean) => void, onSaved: (date: string) => void,
) {
  setError(null);
  setSaving(true);
  try {
    await createSession(initDataRaw, payload);
    onSaved(date);
  } catch (error) {
    setError(error instanceof Error ? error.message : String(error));
    setSaving(false);
  }
}

/** «Другую активность»: дата, тип, длительность ч:мм, усилие, заметка. */
export function FreeActivityForm({
  initDataRaw, onBack, onSaved,
}: {
  initDataRaw: string;
  onBack: () => void;
  onSaved: (date: string) => void;
}) {
  const { timeZone, today } = useProfileToday(initDataRaw);
  const [pickedDate, setDate] = useState<string | null>(null);
  const date = pickedDate ?? today;
  const [activityType, setActivityType] = useState(ACTIVITY_TYPE_OPTIONS[0].value);
  const [duration, setDuration] = useState("");
  const [effort, setEffort] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function save() {
    const problem = dateError(date, today) ?? durationError(duration);
    const payload = problem === null ? buildActivityPayload(date, activityType, duration, effort, note, new Date(), timeZone) : null;
    if (problem !== null || payload === null) {
      setError(problem ?? "Проверь данные");
      return;
    }
    void submit(initDataRaw, date, payload, setError, setSaving, onSaved);
  }

  return (
    <LogFormShell title="Другая активность" error={error} saving={saving} onBack={onBack} onSave={save}>
      <DateField value={date} today={today} onChange={setDate} />
      <div className="log-field">
        <label className="log-label" htmlFor="log-activity-type">Тип</label>
        <select
          id="log-activity-type" className="log-input" value={activityType} data-testid="log-activity-type"
          onChange={(event) => setActivityType(event.target.value)}
        >
          {ACTIVITY_TYPE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </div>
      <div className="log-field">
        <label className="log-label" htmlFor="log-duration">Длительность (ч:мм)</label>
        <input
          id="log-duration" className="log-input" type="text" inputMode="numeric" placeholder="1:30" value={duration}
          data-testid="log-duration" onChange={(event) => setDuration(event.target.value)}
        />
      </div>
      <EffortPicker value={effort} onChange={setEffort} />
      <NoteField value={note} onChange={setNote} />
    </LogFormShell>
  );
}

/** «Тренировку из моих»: свой Workout, дата, значения подходов по упражнениям. */
export function BackdatedWorkoutForm({
  initDataRaw, onBack, onSaved, initialWorkoutId = null,
}: {
  initDataRaw: string;
  /** Предзаполнение из Workout Detail «Записать». */
  initialWorkoutId?: number | null;
  onBack: () => void;
  onSaved: (date: string) => void;
}) {
  const { timeZone, today } = useProfileToday(initDataRaw);
  const [workouts, setWorkouts] = useState<WorkoutResponseV2[] | null>(null);
  const [workoutId, setWorkoutId] = useState<number | null>(initialWorkoutId);
  const [workout, setWorkout] = useState<WorkoutResponseV2 | null>(null);
  const [values, setValues] = useState<Record<number, string[]>>({});
  const [pickedDate, setDate] = useState<string | null>(null);
  const date = pickedDate ?? today;
  const [effort, setEffort] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listWorkouts(initDataRaw)
      .then((all) => {
        if (!cancelled) {
          setWorkouts(all.filter((item) => item.source_type === "user"));
        }
      })
      .catch((loadError) => {
        if (!cancelled) {
          setWorkouts([]);
          setError(loadError instanceof Error ? loadError.message : String(loadError));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  useEffect(() => {
    if (workoutId === null) {
      setWorkout(null);
      return;
    }
    let cancelled = false;
    getWorkout(initDataRaw, workoutId)
      .then((detail) => {
        if (!cancelled) {
          setWorkout(detail);
          setValues({});
        }
      })
      .catch((loadError) => {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : String(loadError));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw, workoutId]);

  const items = workout?.items ?? [];

  function setValue(itemId: number, index: number, count: number, value: string) {
    setValues((current) => {
      const row = [...(current[itemId] ?? Array.from({ length: count }, () => ""))];
      row[index] = value;
      return { ...current, [itemId]: row };
    });
  }

  function save() {
    const problem = dateError(date, today);
    if (problem !== null) {
      setError(problem);
      return;
    }
    const payload = buildBackdatedPayload(
      date,
      items.map((item) => ({ exerciseId: item.exercise_id, protocol: item.protocol, values: values[item.id] ?? [] })),
      effort, note, new Date(), timeZone,
    );
    if (payload === null) {
      setError("Введи хотя бы один подход");
      return;
    }
    void submit(initDataRaw, date, payload, setError, setSaving, onSaved);
  }

  return (
    <LogFormShell title="Тренировка из моих" error={error} saving={saving} onBack={onBack} onSave={save}>
      <div className="log-field">
        <label className="log-label" htmlFor="log-workout">Тренировка</label>
        {workouts !== null && workouts.length === 0 ? (
          <p className="hint" data-testid="log-no-workouts">У тебя пока нет своих тренировок — создай её на Главной.</p>
        ) : (
          <select
            id="log-workout" className="log-input" value={workoutId ?? ""} data-testid="log-workout-select"
            onChange={(event) => setWorkoutId(event.target.value === "" ? null : Number(event.target.value))}
          >
            <option value="">Выбери тренировку</option>
            {(workouts ?? []).map((item) => (
              <option key={item.id} value={item.id}>{item.title}</option>
            ))}
          </select>
        )}
      </div>
      <DateField value={date} today={today} onChange={setDate} />
      {items.map((item) => {
        const count = setCountForProtocol(item.protocol);
        const unitLabel = metricForProtocol(item.protocol).unit === "s" ? "сек" : "повт.";
        return (
          <div className="log-field" key={item.id} data-testid="log-exercise">
            <p className="log-label">{item.exercise_name} · {unitLabel}</p>
            <div className="log-sets">
              {Array.from({ length: count }, (_, index) => (
                <input
                  key={index} className="log-input log-set-input" type="text" inputMode="decimal"
                  aria-label={`${item.exercise_name}, подход ${index + 1}`}
                  data-testid={`log-set-${item.id}-${index}`}
                  value={(values[item.id] ?? [])[index] ?? ""}
                  onChange={(event) => setValue(item.id, index, count, event.target.value)}
                />
              ))}
            </div>
          </div>
        );
      })}
      <EffortPicker value={effort} onChange={setEffort} />
      <NoteField value={note} onChange={setNote} />
    </LogFormShell>
  );
}
