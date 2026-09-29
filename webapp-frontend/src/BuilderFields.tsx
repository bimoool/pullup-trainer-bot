import { useEffect, useState } from "react";

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
  const [text, setText] = useState(() => formatSecondsAsMinutesSeconds(seconds));
  useEffect(() => {
    if (parseMinutesSecondsToSeconds(text) !== seconds) {
      setText(formatSecondsAsMinutesSeconds(seconds));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seconds]);

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
        <button type="button" className="ux-step" aria-label={`Меньше: ${label}`} disabled={seconds <= min} onClick={() => commit(seconds - step)}>
          −
        </button>
        <input
          className="ux-input ux-input-time"
          inputMode="numeric"
          aria-label={label}
          value={text}
          onChange={(event) => {
            setText(event.target.value);
            const parsed = parseMinutesSecondsToSeconds(event.target.value);
            if (parsed !== null) onChange(parsed);
          }}
          onBlur={() => setText(formatSecondsAsMinutesSeconds(seconds))}
        />
        <button type="button" className="ux-step" aria-label={`Больше: ${label}`} onClick={() => commit(seconds + step)}>
          +
        </button>
      </div>
      <span className="ux-unit">мин:сек</span>
    </div>
  );
}
