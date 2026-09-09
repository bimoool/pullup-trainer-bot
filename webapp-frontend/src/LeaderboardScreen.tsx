import { useEffect, useState } from "react";

import {
  fetchLeaderboard,
  updateLeaderboardDisplayName,
  type LeaderboardAgeBucket,
  type LeaderboardData,
  type LeaderboardGender,
  type LeaderboardMetric,
  type LeaderboardPeriod,
} from "./api";

type Props = { initDataRaw: string };

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; data: LeaderboardData };

const METRIC_TABS: { key: LeaderboardMetric; label: string }[] = [
  { key: "max_reps", label: "Повторения" },
  { key: "max_weight", label: "Вес" },
  { key: "total_volume", label: "Объём" },
];

const GENDER_OPTIONS: { key: LeaderboardGender; label: string }[] = [
  { key: "all", label: "Пол: все" },
  { key: "male", label: "Пол: М" },
  { key: "female", label: "Пол: Ж" },
];

// Ступени ГТО для взрослых (app.domain.leaderboard.AGE_BUCKETS, issue #67) —
// готовый ориентир, взятый по запросу автора, не официальный стандарт для
// самого лидерборда.
const AGE_BUCKET_OPTIONS: { key: LeaderboardAgeBucket; label: string }[] = [
  { key: "all", label: "Возраст: все" },
  { key: "18_29", label: "18–29" },
  { key: "30_39", label: "30–39" },
  { key: "40_49", label: "40–49" },
  { key: "50_59", label: "50–59" },
  { key: "60_69", label: "60–69" },
  { key: "70_plus", label: "70+" },
];

// Скользящее окно, не календарное (issue #74, волна 2) — см. пояснение у
// LeaderboardPeriod в api.ts. Виден только на вкладке "Объём" (см. рендер
// ниже) — для max_reps/max_weight период не имеет смысла и бэкенд его
// игнорирует.
const PERIOD_OPTIONS: { key: LeaderboardPeriod; label: string }[] = [
  { key: "week", label: "Неделя" },
  { key: "month", label: "Месяц" },
  { key: "all", label: "Всё время" },
];

/** Целое число повторений/объёма отображается без дробной части даже если
 * бэкенд прислал его как Decimal-строку ("45" или "45.00") — вес, наоборот,
 * оставляем как есть (может быть дробным, "62.5"). */
function formatValue(metric: LeaderboardMetric, value: string): string {
  if (metric === "max_weight") {
    return `${value} кг`;
  }
  return `${Math.trunc(Number(value))}`;
}

/** Вкладка "Лидерборд" (issue #67) — три метрики переключаются табами
 * внутри одного экрана (не три отдельных экрана), фильтр по полу/возрастной
 * категории применяется к любой из них одинаково. Своя строка (если вне
 * видимого топа) показывается отдельно под списком с разделителем — тот же
 * частый паттерн лидербордов, что был согласован в плане issue #67. */
export function LeaderboardScreen({ initDataRaw }: Props) {
  const [metric, setMetric] = useState<LeaderboardMetric>("max_reps");
  const [gender, setGender] = useState<LeaderboardGender>("all");
  const [ageBucket, setAgeBucket] = useState<LeaderboardAgeBucket>("all");
  const [period, setPeriod] = useState<LeaderboardPeriod>("all");
  const [state, setState] = useState<ScreenState>({ phase: "loading" });

  const [nameInput, setNameInput] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setState({ phase: "loading" });
      try {
        const data = await fetchLeaderboard(initDataRaw, metric, gender, ageBucket, period);
        if (!cancelled) {
          setState({ phase: "ready", data });
          setNameInput(data.my_display_name ?? "");
        }
      } catch (error) {
        if (!cancelled) {
          setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [initDataRaw, metric, gender, ageBucket, period]);

  async function handleSaveName() {
    setNameError(null);
    setSavingName(true);
    try {
      const trimmed = nameInput.trim();
      const { display_name: saved } = await updateLeaderboardDisplayName(initDataRaw, trimmed === "" ? null : trimmed);
      setNameInput(saved ?? "");
      if (state.phase === "ready") {
        setState({ phase: "ready", data: { ...state.data, my_display_name: saved } });
      }
    } catch (error) {
      setNameError(error instanceof Error ? error.message : String(error));
    } finally {
      setSavingName(false);
    }
  }

  return (
    <div>
      <p className="plan-title">Лидерборд</p>

      <div className="workout-mode-buttons">
        {METRIC_TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={tab.key === metric ? "leaderboard-tab leaderboard-tab-active" : "leaderboard-tab"}
            onClick={() => setMetric(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {metric === "total_volume" && (
        <div className="workout-mode-buttons">
          {PERIOD_OPTIONS.map((option) => (
            <button
              key={option.key}
              type="button"
              className={option.key === period ? "leaderboard-tab leaderboard-tab-active" : "leaderboard-tab"}
              onClick={() => setPeriod(option.key)}
            >
              {option.label}
            </button>
          ))}
        </div>
      )}

      <div className="leaderboard-filters">
        <select
          className="leaderboard-select"
          value={gender}
          onChange={(event) => setGender(event.target.value as LeaderboardGender)}
        >
          {GENDER_OPTIONS.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
        <select
          className="leaderboard-select"
          value={ageBucket}
          onChange={(event) => setAgeBucket(event.target.value as LeaderboardAgeBucket)}
        >
          {AGE_BUCKET_OPTIONS.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <div className="profile-card">
        <p className="section-title">Отображаемое имя</p>
        <p className="hint">Пусто — участвуешь в лидерборде анонимно (это же дефолт, пока не задано явно).</p>
        <input
          className="leaderboard-name-input"
          type="text"
          maxLength={64}
          placeholder="Аноним"
          value={nameInput}
          onChange={(event) => setNameInput(event.target.value)}
        />
        <button type="button" className="leaderboard-save-button" onClick={() => void handleSaveName()} disabled={savingName}>
          {savingName ? "Сохраняю…" : "Сохранить"}
        </button>
        {nameError && <p className="screen-message">Не удалось сохранить имя: {nameError}</p>}
      </div>

      {state.phase === "loading" && <p className="screen-message">Загружаю лидерборд…</p>}
      {state.phase === "error" && <p className="screen-message">Не удалось загрузить лидерборд: {state.message}</p>}
      {state.phase === "ready" && <LeaderboardTable metric={metric} data={state.data} />}
    </div>
  );
}

/** entries приходят от бэкенда уже отсортированными по rank (топ-N плюс,
 * возможно, своя строка последней) — разрыв между соседними rank в этом же
 * порядке однозначно отмечает место, где строка пользователя "прилипает"
 * снизу списка вне видимого топа (issue #67), без отдельной ветки для
 * "своя строка внутри топа"/"своя строка вне топа". */
function LeaderboardTable({ metric, data }: { metric: LeaderboardMetric; data: LeaderboardData }) {
  if (data.entries.length === 0) {
    return <p className="screen-message">Пока никто не попал в этот срез лидерборда.</p>;
  }

  return (
    <div className="leaderboard-list">
      {data.entries.map((entry, index) => {
        const previous = data.entries[index - 1];
        const showGap = previous !== undefined && entry.rank > previous.rank + 1;
        return (
          <div key={entry.rank}>
            {showGap && <div className="leaderboard-gap">⋯</div>}
            <div className={entry.is_current_user ? "leaderboard-row leaderboard-row-own" : "leaderboard-row"}>
              <span className="leaderboard-rank">#{entry.rank}</span>
              <span className="leaderboard-name">
                {entry.display_name}
                {entry.is_current_user ? " (ты)" : ""}
              </span>
              <span className="leaderboard-value">{formatValue(metric, entry.value)}</span>
            </div>
          </div>
        );
      })}
      {data.my_rank === null && (
        <p className="hint">
          Твоей строки здесь нет — либо ещё нет тренировок для этой метрики, либо не подходишь под выбранный фильтр.
        </p>
      )}
    </div>
  );
}
