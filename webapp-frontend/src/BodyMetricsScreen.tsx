import { Button, Input } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  addBodyMetric,
  deleteBodyMetric,
  fetchBodyMetrics,
  updateBodyMetric,
  type BodyMetricEntry,
  type BodyMetricHistory,
  type BodyMetricKind,
} from "./api";
import { formatMeasuredDate, latestDelta, measuredAtFromDate, toDateInput, trendPoints } from "./bodyMetrics";
import { useDisplayPrefs } from "./displayPrefs";
import { convertHeightText, convertWeightText, formatHeight, formatWeight, unitToCm, unitToKg } from "./units";

type Props = {
  initDataRaw: string;
  metric: BodyMetricKind;
  /** Вызывается после любого изменения истории — профиль перечитывает зеркало User.weight_kg/height_cm. */
  onChanged: () => void;
  onBack: () => void;
};

type Editor = { mode: "add" } | { mode: "edit"; entry: BodyMetricEntry };

const TREND_W = 300;
const TREND_H = 120;
const TITLE: Record<BodyMetricKind, string> = { weight_kg: "Вес", height_cm: "Рост" };

/** История веса/роста (#270): SVG-тренд, список замеров, «Добавить замер», правка и удаление с подтверждением.
 * Последний замер зеркалится бэкендом в User.weight_kg/height_cm (GTO/WSF/лидерборд читают их). */
export function BodyMetricsScreen({ initDataRaw, metric, onChanged, onBack }: Props) {
  const prefs = useDisplayPrefs();
  const [history, setHistory] = useState<BodyMetricHistory | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editor, setEditor] = useState<Editor | null>(null);
  const [valueText, setValueText] = useState("");
  const [dateText, setDateText] = useState(toDateInput(new Date()));
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchBodyMetrics(initDataRaw, metric)
      .then((loaded) => {
        if (!cancelled) {
          setHistory(loaded);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : String(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw, metric]);

  const isWeight = metric === "weight_kg";
  const show = (value: string): string =>
    isWeight ? formatWeight(value, prefs.weight_unit) : formatHeight(Number(value), prefs.height_unit);
  const unitLabel = isWeight ? (prefs.weight_unit === "kg" ? "кг" : "фунты") : prefs.height_unit === "cm" ? "см" : "дюймы";

  function openEditor(next: Editor) {
    setError(null);
    setEditor(next);
    if (next.mode === "edit") {
      const raw = String(Number(next.entry.value));
      setValueText(
        isWeight ? convertWeightText(raw, "kg", prefs.weight_unit) : convertHeightText(raw, "cm", prefs.height_unit),
      );
      setDateText(toDateInput(new Date(next.entry.measured_at)));
    } else {
      setValueText("");
      setDateText(toDateInput(new Date()));
    }
  }

  /** Введённое значение → метрическая строка для API; null — не число. */
  function toApiValue(): string | null {
    const parsed = Number(valueText.trim().replace(",", "."));
    if (valueText.trim() === "" || !Number.isFinite(parsed) || parsed <= 0) {
      return null;
    }
    return String(isWeight ? unitToKg(parsed, prefs.weight_unit) : unitToCm(parsed, prefs.height_unit));
  }

  async function run(action: () => Promise<BodyMetricHistory>): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      setHistory(await action());
      onChanged();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function handleSave() {
    const value = toApiValue();
    if (value === null || editor === null) {
      setError("Введи положительное число.");
      return;
    }
    if (dateText === "") {
      setError("Укажи дату замера.");
      return;
    }
    const now = new Date();
    const ok = await run(() =>
      editor.mode === "add"
        ? addBodyMetric(initDataRaw, { metric, value, measured_at: measuredAtFromDate(dateText, now) })
        : updateBodyMetric(initDataRaw, editor.entry.id, {
            value,
            measured_at: measuredAtFromDate(dateText, now, editor.entry.measured_at),
          }),
    );
    if (ok) {
      setEditor(null);
    }
  }

  async function handleDelete(entry: BodyMetricEntry) {
    if (!window.confirm(`Удалить замер ${show(entry.value)} от ${formatMeasuredDate(entry.measured_at)}?`)) {
      return;
    }
    await run(() => deleteBodyMetric(initDataRaw, entry.id));
  }

  if (loadError !== null) {
    return <p className="screen-message">Не удалось загрузить историю: {loadError}</p>;
  }
  if (history === null) {
    return <p className="screen-message">Загружаю историю…</p>;
  }

  const points = trendPoints(history.items, TREND_W, TREND_H);
  const delta = latestDelta(history.items);
  const polyline = points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");

  return (
    <div data-testid="body-metrics-screen">
      <p className="plan-title">{TITLE[metric]}</p>

      <div className="profile-card">
        <p data-testid="body-metrics-current">{history.current === null ? "Замеров нет" : `Сейчас: ${show(history.current)}`}</p>
        {delta !== null && (
          <p className="hint" data-testid="body-metrics-delta">
            {`К предыдущему замеру: ${delta > 0 ? "+" : ""}${isWeight ? formatWeight(delta, prefs.weight_unit) : formatHeight(delta, prefs.height_unit)}`}
          </p>
        )}
        {points.length >= 2 ? (
          <svg
            className="body-metrics-trend"
            data-testid="body-metrics-trend"
            viewBox={`0 0 ${TREND_W} ${TREND_H}`}
            role="img"
            aria-label={`График: ${TITLE[metric]}`}
          >
            <polyline points={polyline} fill="none" stroke="currentColor" strokeWidth={2} strokeLinejoin="round" />
            {points.map((p, i) => (
              <circle key={i} cx={p.x} cy={p.y} r={3.5} fill="currentColor" />
            ))}
          </svg>
        ) : (
          <p className="hint" data-testid="body-metrics-trend-empty">Для графика нужно минимум два замера.</p>
        )}
      </div>

      {error && <p className="error-banner" data-testid="body-metrics-error">{error}</p>}

      {editor === null ? (
        <Button className="vs-primary" mode="filled" size="m" stretched data-testid="body-metrics-add" onClick={() => openEditor({ mode: "add" })}>
          ➕ Добавить замер
        </Button>
      ) : (
        <div className="profile-card vs-form-card" data-testid="body-metrics-form">
          <p className="section-title">{editor.mode === "add" ? "Новый замер" : "Правка замера"}</p>
          <Input
            header={`${TITLE[metric]}, ${unitLabel}`}
            type="number"
            inputMode="decimal"
            min={0}
            step="0.1"
            aria-label={`${TITLE[metric]} замера`}
            data-testid="body-metrics-value"
            value={valueText}
            onChange={(e) => setValueText(e.target.value)}
          />
          <Input
            header="Дата"
            type="date"
            aria-label="Дата замера"
            data-testid="body-metrics-date"
            max={toDateInput(new Date())}
            value={dateText}
            onChange={(e) => setDateText(e.target.value)}
          />
          <div className="band-create-actions">
            <Button className="vs-primary vs-inline" mode="filled" size="s" disabled={busy} data-testid="body-metrics-save" onClick={() => void handleSave()}>
              {busy ? "Сохраняю…" : "Сохранить"}
            </Button>
            <Button className="vs-secondary vs-inline" mode="outline" size="s" disabled={busy} data-testid="body-metrics-cancel" onClick={() => setEditor(null)}>
              Отмена
            </Button>
          </div>
        </div>
      )}

      <div className="history-list vs-rows" data-testid="body-metrics-list">
        {history.items.map((entry) => (
          <div className="history-card" data-testid="body-metrics-row" key={entry.id}>
            <p>
              <span data-testid="body-metrics-row-date">{formatMeasuredDate(entry.measured_at)}</span>
              {" · "}
              <strong data-testid="body-metrics-row-value">{show(entry.value)}</strong>
            </p>
            <div className="band-create-actions">
              <Button className="vs-chip" mode="outline" size="s" disabled={busy} data-testid="body-metrics-edit" onClick={() => openEditor({ mode: "edit", entry })}>
                Изменить
              </Button>
              <Button className="vs-chip" mode="outline" size="s" disabled={busy} data-testid="body-metrics-delete" onClick={() => void handleDelete(entry)}>
                Удалить
              </Button>
            </div>
          </div>
        ))}
      </div>

      <Button className="vs-secondary" mode="outline" size="m" stretched data-testid="body-metrics-back" onClick={onBack}>
        ← Назад
      </Button>
    </div>
  );
}
