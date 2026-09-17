import { Button, Cell, Input, Placeholder, Section, Select, SegmentedControl, Spinner } from "@telegram-apps/telegram-ui";
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

// Пояснение под табами (issue #74, волна 3.2) — подписи табов сами по
// себе не объясняли методику подсчёта (максимум за один подход, порог
// повторений для веса, наличие периода у объёма).
const METRIC_HINTS: Record<LeaderboardMetric, string> = {
  max_reps: "Максимум повторений за один подход — за всю историю тренировок.",
  max_weight: "Максимальный вес отягощения, на котором выполнено хотя бы 3 повторения в одном подходе.",
  total_volume: "Суммарные повторения по обоим блокам за выбранный период (переключатель ниже).",
};

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
 * частый паттерн лидербордов, что был согласован в плане issue #67.
 *
 * `SegmentedControl`/`Select`/`Section`+`Cell`/`Placeholder` вместо
 * `.leaderboard-tab`/`.leaderboard-select`/`.leaderboard-list`/
 * `.leaderboard-row`/`.screen-message` (issue #142) — тот же базовый
 * паттерн, что AchievementsScreen.tsx. `.leaderboard-tab`/
 * `.leaderboard-tab-active` в index.css не удалены — ProgressScreen.tsx
 * (не тронут этим PR, встраивает LeaderboardScreen целиком) переиспользует
 * те же классы для своего переключателя "График"/"Лидерборд" и для своих
 * табов метрик графика. */
export function LeaderboardScreen({ initDataRaw }: Props) {
  const [metric, setMetric] = useState<LeaderboardMetric>("max_reps");
  const [gender, setGender] = useState<LeaderboardGender>("all");
  const [ageBucket, setAgeBucket] = useState<LeaderboardAgeBucket>("all");
  const [period, setPeriod] = useState<LeaderboardPeriod>("all");
  const [state, setState] = useState<ScreenState>({ phase: "loading" });

  const [nameInput, setNameInput] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);
  // issue #74, волна 3.1 — раньше успешное сохранение не давало никакой
  // видимой реакции (кроме сброса disabled на кнопке), пользователь не
  // понимал, сработало ли, не перезагрузив экран. true только до следующей
  // правки поля (см. onChange ниже) — не "залипает" после следующего ввода.
  const [nameJustSaved, setNameJustSaved] = useState(false);

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
    setNameJustSaved(false);
    setSavingName(true);
    try {
      const trimmed = nameInput.trim();
      const { display_name: saved } = await updateLeaderboardDisplayName(initDataRaw, trimmed === "" ? null : trimmed);
      setNameInput(saved ?? "");
      setNameJustSaved(true);
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

      <SegmentedControl>
        {METRIC_TABS.map((tab) => (
          <SegmentedControl.Item key={tab.key} selected={tab.key === metric} onClick={() => setMetric(tab.key)}>
            {tab.label}
          </SegmentedControl.Item>
        ))}
      </SegmentedControl>
      <p className="hint">{METRIC_HINTS[metric]}</p>

      {metric === "total_volume" && (
        <SegmentedControl>
          {PERIOD_OPTIONS.map((option) => (
            <SegmentedControl.Item key={option.key} selected={option.key === period} onClick={() => setPeriod(option.key)}>
              {option.label}
            </SegmentedControl.Item>
          ))}
        </SegmentedControl>
      )}

      <Select
        aria-label="Пол"
        value={gender}
        onChange={(event) => setGender(event.target.value as LeaderboardGender)}
      >
        {GENDER_OPTIONS.map((option) => (
          <option key={option.key} value={option.key}>
            {option.label}
          </option>
        ))}
      </Select>
      <Select
        aria-label="Возраст"
        value={ageBucket}
        onChange={(event) => setAgeBucket(event.target.value as LeaderboardAgeBucket)}
      >
        {AGE_BUCKET_OPTIONS.map((option) => (
          <option key={option.key} value={option.key}>
            {option.label}
          </option>
        ))}
      </Select>

      <Section header="Отображаемое имя">
        <Cell subtitle="Пусто — участвуешь в лидерборде анонимно (это же дефолт, пока не задано явно).">Имя</Cell>
        <Input
          type="text"
          maxLength={64}
          placeholder="Аноним"
          aria-label="Отображаемое имя"
          value={nameInput}
          onChange={(event) => {
            setNameInput(event.target.value);
            setNameJustSaved(false);
          }}
        />
        <Button size="m" stretched onClick={() => void handleSaveName()} loading={savingName}>
          {savingName ? "Сохраняю…" : "Сохранить"}
        </Button>
        {nameJustSaved && <p className="hint leaderboard-name-saved">✓ Сохранено</p>}
        {nameError && <Placeholder description={`Не удалось сохранить имя: ${nameError}`} />}
      </Section>

      {state.phase === "loading" && (
        <Placeholder>
          <Spinner size="m" />
        </Placeholder>
      )}
      {state.phase === "error" && <Placeholder description={`Не удалось загрузить лидерборд: ${state.message}`} />}
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
    return <Placeholder description="Пока никто не попал в этот срез лидерборда." />;
  }

  return (
    <Section>
      {data.entries.map((entry, index) => {
        const previous = data.entries[index - 1];
        const showGap = previous !== undefined && entry.rank > previous.rank + 1;
        return (
          <div key={entry.rank}>
            {showGap && <div className="leaderboard-gap">⋯</div>}
            <Cell
              subhead={`#${entry.rank}`}
              hint={formatValue(metric, entry.value)}
              subtitle={entry.is_current_user ? "Это ты" : undefined}
            >
              {entry.display_name}
            </Cell>
          </div>
        );
      })}
      {data.my_rank === null && (
        <p className="hint">
          Твоей строки здесь нет — либо ещё нет тренировок для этой метрики, либо не подходишь под выбранный фильтр.
        </p>
      )}
    </Section>
  );
}
