import { useState } from "react";

import { ProgressScreen } from "./ProgressScreen";
import { TrainingAnalytics } from "./TrainingAnalytics";

type Props = { initDataRaw: string };

type Mode = "training" | "program";

const MODES: { key: Mode; label: string }[] = [
  { key: "training", label: "Тренировки" },
  { key: "program", label: "Программа" },
];

/** Вкладка "Аналитика": сверху переключатель "Тренировки | Программа".
 * По умолчанию — "Тренировки" (Analytics v2, TrainingSession); прежняя
 * аналитика программы (график/лидерборд/динамика) целиком под "Программа".
 * Оба режима грузят данные независимо — сбой одного не роняет другой. */
export function AnalyticsScreen({ initDataRaw }: Props) {
  const [mode, setMode] = useState<Mode>("training");
  return (
    <div>
      <p className="plan-title">Аналитика</p>
      <div className="workout-mode-buttons" role="tablist" aria-label="Раздел аналитики">
        {MODES.map((option) => (
          <button
            key={option.key}
            type="button"
            role="tab"
            aria-selected={option.key === mode}
            className={option.key === mode ? "leaderboard-tab leaderboard-tab-active" : "leaderboard-tab"}
            onClick={() => setMode(option.key)}
          >
            {option.label}
          </button>
        ))}
      </div>
      {mode === "training" ? <TrainingAnalytics initDataRaw={initDataRaw} /> : <ProgressScreen initDataRaw={initDataRaw} />}
    </div>
  );
}
