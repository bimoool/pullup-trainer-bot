import { Button, Section } from "@telegram-apps/telegram-ui";
import { useEffect, useState } from "react";

import { fetchDashboard, type DashboardResponse } from "./api";
import { fetchPlan, type ProgramInclusionResponseV2 } from "./apiV2";
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
 * поэтому стрик показывается как число только от 2.
 *
 * Экспортирована (issue #183, волна 5b) — тот же расчёт нужен компактному
 * виджету недели на "Главной" (HomeScreen.tsx), не только полной карточке
 * здесь на "Планах". */
export function streakValue(streak: number, workoutsCount: number): string {
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
  // Подключённые курсы (Capability A, issue #188) — минимальный видимый
  // результат "Добавить в план" (10.2: "внизу Подключённые курсы"). Отдельный
  // эффект и молчаливый провал (пустой массив), чтобы не рвать уже рабочую
  // сводку "Сегодня", если /api/v2/plan недоступен по какой-то причине.
  const [inclusions, setInclusions] = useState<ProgramInclusionResponseV2[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchPlan(initDataRaw)
      .then((plan) => {
        if (!cancelled) {
          setInclusions((plan?.program_inclusions ?? []).filter((i) => i.is_active));
        }
      })
      .catch(() => {
        // молчаливо — см. комментарий у объявления state выше
      });
    return () => {
      cancelled = true;
    };
  }, [initDataRaw]);

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

      {inclusions.length > 0 && (
        <>
          <p className="section-title">Подключённые курсы</p>
          {inclusions.map((inclusion) => (
            <Section key={inclusion.id} className="block-section">
              <p className="block-subtitle">{inclusion.program_name}</p>
            </Section>
          ))}
        </>
      )}

      <Button className="action-button" size="l" stretched onClick={onOpenWorkout}>
        {isReady ? "Начать тренировку" : "Открыть «Тренировку»"}
      </Button>
    </div>
  );
}
