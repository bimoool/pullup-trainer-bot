import { Button, Section } from "@telegram-apps/telegram-ui";

/** Phase C5/D3 (issue #188) — общие day labels, один источник для
 * AddToPlanScreen.tsx и MovePlanItemScreen.tsx, не дублируются. */
export const DAY_LABELS: { value: number; label: string }[] = [
  { value: 0, label: "Пн" }, { value: 1, label: "Вт" }, { value: 2, label: "Ср" },
  { value: 3, label: "Чт" }, { value: 4, label: "Пт" }, { value: 5, label: "Сб" }, { value: 6, label: "Вс" },
];

type Props = {
  selectedDay: number | "free_pool" | null;
  onSelect: (day: number | "free_pool") => void;
};

/**
 * Phase D3 (issue #188) — вынесен из AddToPlanScreen.tsx (изначально
 * реализован в C5a) в отдельный переиспользуемый компонент, чтобы
 * MovePlanItemScreen.tsx не дублировал ту же разметку/CSS второй раз
 * (issue #188, раздел 7 — "не копировать второй раз, не устраивать
 * большой refactor" — минимальное извлечение, сама разметка/стили
 * не изменены).
 */
export function DayPicker({ selectedDay, onSelect }: Props) {
  return (
    <Section className="block-section" header="День">
      <div className="week-day-picker">
        {DAY_LABELS.map(({ value, label }) => (
          <Button
            key={value} size="s"
            mode={selectedDay === value ? "filled" : "outline"}
            onClick={() => onSelect(value)}
          >
            {label}
          </Button>
        ))}
      </div>
      <Button
        size="s" stretched
        mode={selectedDay === "free_pool" ? "filled" : "outline"}
        onClick={() => onSelect("free_pool")}
      >
        Свободный пул
      </Button>
    </Section>
  );
}
