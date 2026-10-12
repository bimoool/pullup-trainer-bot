/**
 * Поля формы с ВИДИМОЙ подписью, которая переносится на несколько строк.
 *
 * `header` у Input/Select из telegram-ui — однострочный ellipsis-лейбл: на ios он плавает внутри поля,
 * на base/android лежит над полем, и длинная подпись («…закрыли 5×5 (сила A)…») обрезается. Здесь подпись —
 * обычный `<label htmlFor>` над полем: она же accessible name поля, на всех платформах и ширинах (320/390)
 * видна целиком. placeholder и aria-label подпись не заменяют.
 */
import { Input, Select } from "@telegram-apps/telegram-ui";
import { type ComponentProps, type ReactNode, useId } from "react";

type InputProps = Omit<ComponentProps<typeof Input>, "header" | "id" | "aria-label">;
type SelectProps = Omit<ComponentProps<typeof Select>, "header" | "id" | "aria-label">;

function Caption({ id, label, hint }: { id: string; label: ReactNode; hint?: ReactNode }) {
  return (
    <>
      <label htmlFor={id} className="labeled-field-caption">{label}</label>
      {hint !== undefined && <p className="labeled-field-hint">{hint}</p>}
    </>
  );
}

export function LabeledInput({ label, hint, ...rest }: InputProps & { label: ReactNode; hint?: ReactNode }) {
  const id = useId();
  return (
    <div className="labeled-field">
      <Caption id={id} label={label} hint={hint} />
      <Input id={id} {...rest} />
    </div>
  );
}

export function LabeledSelect({ label, hint, children, ...rest }: SelectProps & { label: ReactNode; hint?: ReactNode }) {
  const id = useId();
  return (
    <div className="labeled-field">
      <Caption id={id} label={label} hint={hint} />
      <Select id={id} {...rest}>{children}</Select>
    </div>
  );
}
