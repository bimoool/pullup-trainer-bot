import { useState } from "react";

import { createExportLink } from "./apiV2";
import { type ExportWebApp, startDownload } from "./exportDownload";
import { ProgressScreen } from "./ProgressScreen";
import { TrainingAnalytics } from "./TrainingAnalytics";

type Props = { initDataRaw: string };

type Mode = "training" | "program";

const MODES: { key: Mode; label: string }[] = [
  { key: "training", label: "Тренировки" },
  { key: "program", label: "Программа" },
];

/** Карточка «Экспорт данных — CSV» (#267): подписанная ссылка → downloadFile в Telegram, иначе открыть. */
function ExportCard({ initDataRaw }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function download() {
    setBusy(true);
    setError(null);
    try {
      const { url } = await createExportLink(initDataRaw);
      const webApp = (window as unknown as { Telegram?: { WebApp?: ExportWebApp } }).Telegram?.WebApp;
      startDownload(url, { webApp, origin: window.location.origin, open: (target) => window.open(target, "_blank") });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось подготовить файл");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="profile-card" data-testid="export-card">
      <p className="section-title">Экспорт данных — CSV</p>
      <p className="hint">Вся история тренировок: по строке на подход, открывается в Excel.</p>
      <button type="button" className="action-button" data-testid="export-download" disabled={busy} onClick={download}>
        Скачать
      </button>
      {error && <p className="error-banner"data-testid="export-error" role="alert">{error}</p>}
    </div>
  );
}

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
      <ExportCard initDataRaw={initDataRaw} />
    </div>
  );
}
