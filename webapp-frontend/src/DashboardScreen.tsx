import { Button } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchDashboard, type DashboardResponse } from "./api";
import { STATUS_MESSAGES } from "./WorkoutScreen";

type Props = {
  initDataRaw: string;
  /** Быстрый старт (issue #175) — переключает нижнюю вкладку на
   * "Тренировку" (App.tsx), сама форма живёт там же, где и раньше: Dashboard
   * не дублирует WorkoutScreen, только не открывается на нём по умолчанию
   * (product-reference skill: стартовый экран — сводка, не открытая
   * тренировка). */
  onOpenWorkout: () => void;
};

type ScreenState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; dashboard: DashboardResponse };

/** Та же нижняя граница, что у app.domain.achievements.consecutive_streak_length:
 * 1 — единственная тренировка, это ещё не "серия" в разговорном смысле,
 * поэтому стрик показывается как число только от 2. */
function streakValue(streak: number, workoutsCount: number): string {
  if (workoutsCount === 0 || streak <= 1) {
    return "—";
  }
  return `🔥 ${streak}`;
}

function daysSinceLabel(days: number | null): string {
  if (days === null) {
    return "—";
  }
  if (days === 0) {
    return "Сегодня";
  }
  return `${days} дн. назад`;
}

/** Только честные статусы (issue #175, docs/architecture-multicourse.md:
 * "нельзя предлагать действие, которое гарантированно не может завершиться
 * успехом") — кнопка ниже обещает "начать тренировку" ТОЛЬКО на status=
 * "ready". На любом другом статусе она просто открывает раздел "Тренировка",
 * где WorkoutScreen (тот же STATUS_MESSAGES) объясняет причину и предлагает
 * то, что реально доступно (факультатив/бэкдейт/бот) — Dashboard не
 * дублирует эту логику, только не начинает с неё. */
export function DashboardScreen({ initDataRaw, onOpenWorkout }: Props) {
  const [state, setState] = useState<ScreenState>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetchDashboard(initDataRaw)
      .then((dashboard) => {
        if (!cancelled) {
          setState({ phase: "ready", dashboard });
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setState({ phase: "error", message: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

  if (state.phase === "loading") {
    return <p className="screen-message">Загружаю…</p>;
  }
  if (state.phase === "error") {
    return <p className="screen-message">Не удалось загрузить: {state.message}</p>;
  }

  const { dashboard } = state;
  const isReady = dashboard.status === "ready";

  let statusText: string;
  if (isReady && dashboard.is_first_workout) {
    statusText = "Это будет твоя первая тренировка — сначала подберём снаряд по замеру.";
  } else if (isReady) {
    statusText = "Готов к тренировке.";
  } else {
    statusText = STATUS_MESSAGES[dashboard.status] ?? `Статус: ${dashboard.status}`;
  }

  return (
    <div>
      <p className="plan-title">Сегодня</p>

      <div className="stat-grid">
        <div className="stat-tile">
          <div className="stat-value">{dashboard.workouts_count}</div>
          <div className="stat-label">Тренировок всего</div>
        </div>
        <div className="stat-tile">
          <div className="stat-value">{streakValue(dashboard.streak, dashboard.workouts_count)}</div>
          <div className="stat-label">Подряд без перерыва</div>
        </div>
        <div className="stat-tile">
          <div className="stat-value">{daysSinceLabel(dashboard.days_since_last_workout)}</div>
          <div className="stat-label">Последняя тренировка</div>
        </div>
      </div>

      <p className="screen-message">{statusText}</p>

      <Button className="action-button" size="l" stretched onClick={onOpenWorkout}>
        {isReady ? "Начать тренировку" : "Открыть «Тренировку»"}
      </Button>
    </div>
  );
}
