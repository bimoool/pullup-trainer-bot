import { Spinner } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import {
  createAssessmentResult, deleteAssessmentResult, getAssessment, updateAssessmentResult,
  type AssessmentProtocolV2, type AssessmentResultV2,
} from "./apiV2";
import {
  bestValue, chartPoints, formatIsoDate, formatValue, NOT_IN_PROGRESSION_NOTE, pathFor, validateResultForm,
} from "./assessmentsFormat";
import { PeerInsightsCard } from "./PeerInsightsCard";
import { useBackButton } from "./useBackButton";

type Props = { initDataRaw: string; protocolId: number; onBack: () => void };

type DetailState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; protocol: AssessmentProtocolV2; results: AssessmentResultV2[] };

const CHART_W = 320;
const CHART_H = 150;
const SERIES_COLOR = "#2a78d6";

function todayIsoDate(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function TrendChart({ results, unit, name }: { results: AssessmentResultV2[]; unit: string; name: string }) {
  if (results.length < 2) {
    return <p className="hint" data-testid="test-chart-empty">Для графика нужно хотя бы два результата.</p>;
  }
  const chronological = [...results].reverse();
  const values = chronological.map((r) => Number(r.value));
  const points = chartPoints(values, CHART_W, CHART_H, 24);
  const ariaLabel = `${name}: ${chronological.map((r) => `${formatIsoDate(r.performed_on)} — ${r.value}`).join(", ")}`;
  return (
    <svg
      viewBox={`0 0 ${CHART_W} ${CHART_H}`} className="analytics-trend-chart" role="img" aria-label={ariaLabel}
      data-testid="test-chart" data-points={values.length}
    >
      <path d={pathFor(points)} fill="none" stroke={SERIES_COLOR} strokeWidth="2" strokeLinejoin="round" />
      {points.map((p, i) => <circle key={chronological[i].id} cx={p.x} cy={p.y} r="3" fill={SERIES_COLOR} />)}
      <text x={4} y={14} fontSize="10" fill="currentColor" opacity="0.7">{`макс. ${bestValue(values)} ${unit}`}</text>
      <text x={4} y={CHART_H - 6} fontSize="10" fill="currentColor" opacity="0.7">{formatIsoDate(chronological[0].performed_on)}</text>
      <text x={CHART_W - 4} y={CHART_H - 6} fontSize="10" textAnchor="end" fill="currentColor" opacity="0.7">
        {formatIsoDate(chronological[chronological.length - 1].performed_on)}
      </text>
    </svg>
  );
}

/** Деталь теста: описание, график, форма «Записать результат», история с правкой/удалением.
 * Результаты не влияют на прогрессию и стартовый замер — об этом сказано на экране. */
export function TestDetailScreen({ initDataRaw, protocolId, onBack }: Props) {
  const [state, setState] = useState<DetailState>({ phase: "loading" });
  const [editingId, setEditingId] = useState<number | null>(null);
  const [performedOn, setPerformedOn] = useState(todayIsoDate());
  const [value, setValue] = useState("");
  const [note, setNote] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useBackButton(onBack, [onBack]);

  function reload() {
    return getAssessment(initDataRaw, protocolId)
      .then(({ protocol, results }) => setState({ phase: "ready", protocol, results }))
      .catch((error) => setState({ phase: "error", message: error instanceof Error ? error.message : String(error) }));
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- загрузка при смене теста
  }, [initDataRaw, protocolId]);

  if (state.phase === "loading") {
    return <Spinner size="m" />;
  }
  if (state.phase === "error") {
    return <p className="gap-banner">Не удалось загрузить: {state.message}</p>;
  }

  const { protocol, results } = state;

  function resetForm() {
    setEditingId(null);
    setPerformedOn(todayIsoDate());
    setValue("");
    setNote("");
    setFormError(null);
  }

  function startEdit(result: AssessmentResultV2) {
    setEditingId(result.id);
    setPerformedOn(result.performed_on);
    setValue(result.value);
    setNote(result.note ?? "");
    setFormError(null);
  }

  async function submit() {
    const checked = validateResultForm({ performedOn, value, note }, todayIsoDate(), protocol.metric_type === "reps");
    if (!checked.ok) {
      setFormError(checked.error);
      return;
    }
    const input = { performed_on: checked.performedOn, value: checked.value, note: checked.note };
    setSaving(true);
    try {
      if (editingId === null) {
        await createAssessmentResult(initDataRaw, protocol.id, input);
      } else {
        await updateAssessmentResult(initDataRaw, editingId, input);
      }
      resetForm();
      await reload();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  }

  async function remove(result: AssessmentResultV2) {
    const label = `${formatValue(result.value, result.unit)} от ${formatIsoDate(result.performed_on)}`;
    if (!window.confirm(`Удалить результат ${label}?`)) {
      return;
    }
    try {
      await deleteAssessmentResult(initDataRaw, result.id);
      if (editingId === result.id) {
        resetForm();
      }
      await reload();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <div data-testid="test-detail">
      <p className="plan-title" data-testid="test-detail-title">{protocol.name}</p>
      {protocol.description && <p className="hint" data-testid="test-detail-description">{protocol.description}</p>}
      <p className="hint" data-testid="test-detail-note">{NOT_IN_PROGRESSION_NOTE}</p>

      <p className="section-title">Динамика</p>
      <TrendChart results={results} unit={protocol.unit} name={protocol.name} />

      <PeerInsightsCard
        initDataRaw={initDataRaw} protocolId={protocol.id} integerOnly={protocol.metric_type === "reps"}
        refreshKey={`${results[0]?.id ?? 0}:${results[0]?.value ?? ""}:${results[0]?.performed_on ?? ""}`}
      />

      <div className="profile-card" data-testid="test-form">
        <p className="section-title">{editingId === null ? "Записать результат" : "Изменить результат"}</p>
        <label className="field-label" htmlFor="test-date">Дата</label>
        <input
          id="test-date" type="date" className="set-input" max={todayIsoDate()} value={performedOn}
          onChange={(e) => setPerformedOn(e.target.value)}
        />
        <label className="field-label" htmlFor="test-value">{`Результат, ${protocol.unit}`}</label>
        <input
          id="test-value" type="text" inputMode="decimal" className="set-input" value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <label className="field-label" htmlFor="test-note">Заметка (необязательно)</label>
        <input
          id="test-note" type="text" className="set-input" maxLength={500} value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        {formError && <p className="favorite-error" role="alert" data-testid="test-form-error">{formError}</p>}
        <div className="test-actions">
          <button type="button" className="workout-detail-action" disabled={saving} onClick={() => void submit()}>
            <span className="workout-detail-action-label">{editingId === null ? "Записать результат" : "Сохранить"}</span>
          </button>
          {editingId !== null && (
            <button type="button" className="workout-detail-action" onClick={resetForm}>
              <span className="workout-detail-action-label">Отмена</span>
            </button>
          )}
        </div>
      </div>

      <p className="section-title">История</p>
      {results.length === 0 ? (
        <p className="screen-message" data-testid="test-history-empty">Ещё не проходили</p>
      ) : (
        <ul className="home-workout-list" data-testid="test-history">
          {results.map((result) => (
            <li key={result.id} className="workout-detail-item test-history-row" data-testid="test-history-row">
              <span className="test-history-main">
                <span className="home-workout-title">{formatValue(result.value, result.unit)}</span>
                <span className="home-workout-meta" style={{ whiteSpace: "normal" }}>
                  {formatIsoDate(result.performed_on)}{result.note ? ` · ${result.note}` : ""}
                </span>
              </span>
              <span className="test-history-actions">
                <button type="button" className="test-row-button" aria-label={`Изменить результат от ${formatIsoDate(result.performed_on)}`} onClick={() => startEdit(result)}>
                  Изменить
                </button>
                <button type="button" className="test-row-button" aria-label={`Удалить результат от ${formatIsoDate(result.performed_on)}`} onClick={() => void remove(result)}>
                  Удалить
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
