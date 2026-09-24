import { Input } from "@telegram-apps/telegram-ui";
import { useState } from "react";

import { formatSecondsAsMinutesSeconds, parseMinutesSecondsToSeconds } from "./timeInput";

type Props = {
  header: string;
  /** Текущее значение в секундах — источник правды остаётся числом
   * (секунды), поле только отображает/принимает его как мм:сс. */
  seconds: number;
  onChange: (seconds: number) => void;
};

/**
 * Phase C4b-1 (issue #188) — один переиспользуемый мм:сс input для всех
 * четырёх protocol-форм (reps/time/max/interval), не 4 независимые
 * реализации. Пока пользователь печатает невалидную строку (например
 * "1:"), локальный text-state сохраняет её как есть для удобства ввода,
 * onChange наружу не вызывается — родитель узнаёт только о валидных
 * значениях. При потере фокуса невалидный ввод откатывается обратно на
 * последнее валидное значение.
 */
export function TimeInputField({ header, seconds, onChange }: Props) {
  const [text, setText] = useState(() => formatSecondsAsMinutesSeconds(seconds));

  function handleChange(value: string) {
    setText(value);
    const parsed = parseMinutesSecondsToSeconds(value);
    if (parsed !== null) {
      onChange(parsed);
    }
  }

  function handleBlur() {
    // Откат на последнее валидное значение, если пользователь ушёл с
    // поля с недописанной/невалидной строкой.
    setText(formatSecondsAsMinutesSeconds(seconds));
  }

  return (
    <Input
      header={header}
      value={text}
      placeholder="мм:сс"
      onChange={(event) => handleChange(event.target.value)}
      onBlur={handleBlur}
    />
  );
}
