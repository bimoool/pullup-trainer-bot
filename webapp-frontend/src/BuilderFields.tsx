import { useEffect, useId, useState } from "react";

import { formatSecondsAsMinutesSeconds, parseMinutesSecondsToSeconds } from "./timeInput";

/**
 * UX-1 — поля Builder-формы. Подпись слева, значение справа, явные −/+ (44 px,
 * как в референсе), значение — настоящее поле ввода с рамкой и aria-label, единица
 * измерения видна. Источник правды — число в родителе; локальный text только для
 * набора (пустое/неполное значение не превращается в NaN в родителе молча:
 * пустое → NaN → валидация формы честно просит заполнить).
 */

type StepperProps = {
  label: string;
  hint?: string;
  unit?: string;
  value: number;
  min?: number;
  max?: number;
  onChange: (value: number) => void;
};

export function StepperRow({ label, hint, unit, value, min = 1, max = 999, onChange }: StepperProps) {
  const [text, setText] = useState(String(value));
  useEffect(() => {
    if (Number(text) !== value && !(Number.isNaN(value) && text.trim() === "")) {
      setText(Number.isNaN(value) ? "" : String(value));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  function commit(next: number) {
    const clamped = Math.min(max, Math.max(min, next));
    setText(String(clamped));
    onChange(clamped);
  }

  const current = Number.isNaN(value) ? min - 1 : value;
  return (
    <div className="ux-row" data-testid={`field-${label}`}>
      <div className="ux-row-label">
        <span className="ux-row-title">{label}</span>
        {hint && <span className="ux-row-hint">{hint}</span>}
      </div>
      <div className="ux-control">
        <button type="button" className="ux-step" aria-label={`Меньше: ${label}`} disabled={current <= min} onClick={() => commit(current - 1)}>
          −
        </button>
        <input
          className="ux-input"
          inputMode="numeric"
          aria-label={label}
          value={text}
          onChange={(event) => {
            const cleaned = event.target.value.replace(/[^\d]/g, "");
            setText(cleaned);
            onChange(cleaned === "" ? NaN : Number(cleaned));
          }}
          onBlur={() => setText(Number.isNaN(value) ? "" : String(value))}
        />
        <button type="button" className="ux-step" aria-label={`Больше: ${label}`} disabled={current >= max} onClick={() => commit(current + 1)}>
          +
        </button>
      </div>
      {unit && <span className="ux-unit">{unit}</span>}
    </div>
  );
}

type TimeProps = {
  label: string;
  hint?: string;
  seconds: number;
  step?: number;
  min?: number;
  onChange: (seconds: number) => void;
};

export function TimeRow({ label, hint, seconds, step = 5, min = 0, onChange }: TimeProps) {
  const errorId = useId();
  const [text, setText] = useState(() => Number.isFinite(seconds) ? formatSecondsAsMinutesSeconds(seconds) : "");
  useEffect(() => {
    if (Number.isFinite(seconds) && parseMinutesSecondsToSeconds(text) !== seconds) {
      setText(formatSecondsAsMinutesSeconds(seconds));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seconds]);

  const parsed = parseMinutesSecondsToSeconds(text);
  const invalid = parsed === null || parsed < min;

  function commit(next: number) {
    const clamped = Math.max(min, next);
    setText(formatSecondsAsMinutesSeconds(clamped));
    onChange(clamped);
  }

  return (
    <div className="ux-row" data-testid={`field-${label}`}>
      <div className="ux-row-label">
        <span className="ux-row-title">{label}</span>
        {hint && <span className="ux-row-hint">{hint}</span>}
      </div>
      <div className="ux-control">
        <button type="button" className="ux-step" aria-label={`Меньше: ${label}`} disabled={!Number.isFinite(seconds) || seconds <= min} onClick={() => commit(seconds - step)}>
          −
        </button>
        <input
          className="ux-input ux-input-time"
          inputMode="numeric"
          aria-label={label}
          aria-invalid={invalid}
          aria-describedby={invalid ? errorId : undefined}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            const parsed = parseMinutesSecondsToSeconds(event.target.value);
            onChange(parsed ?? NaN);
          }}
          onBlur={() => {
            if (!invalid) setText(formatSecondsAsMinutesSeconds(seconds));
          }}
        />
        <button type="button" className="ux-step" aria-label={`Больше: ${label}`} onClick={() => commit((Number.isFinite(seconds) ? seconds : min) + step)}>
          +
        </button>
      </div>
      <span className="ux-unit">мин:сек</span>
      {invalid && <span className="ux-error" id={errorId} role="alert">{label}: укажите время в формате мин:сек{min > 0 ? " больше нуля" : " (например, 01:30)"}</span>}
    </div>
  );
}
